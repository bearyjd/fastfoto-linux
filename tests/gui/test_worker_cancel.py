"""How long Cancel takes end to end: the worker, the real session and runner, a fake scanimage.

The fake ignores SIGTERM, as scanimage does while it sits in its exit path (it retries ``FIN``
for about a minute), so only the grace period ends the wait. The grace is shortened for the test;
what is checked is that nothing else adds to it.
"""

import threading
import time
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any

import pytest

from fastfoto_linux.gui.form import ScanForm
from fastfoto_linux.gui.worker import Worker
from fastfoto_linux.scanner import ScanTarget, run_scan
from fastfoto_linux.scanner import run as run_module
from fastfoto_linux.session import SessionResult, run_session
from tests._fake_scanimage import fake_env, install
from tests.cli.fakes import DEVICE
from tests.gui.helpers import RecordingSink

DEFAULT_GRACE_S = run_module.TERMINATE_GRACE_S  # before the tests shorten it
GRACE_S = 0.4
SLACK_S = 1.0  # the contract: Cancel finishes within the grace period plus a second
WAIT_S = 10.0
TIMEOUT_S = 8.0  # a scan that is never stopped gives up here instead of hanging the suite


@pytest.fixture
def form(out: Path) -> ScanForm:
    return ScanForm(output_folder=str(out))


@pytest.fixture
def fake_scanimage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    def configure(**spec: Any) -> None:
        for name, value in fake_env(install(tmp_path / "bin"), **spec).items():
            monkeypatch.setenv(name, value)

    return configure


@pytest.fixture(autouse=True)
def short_grace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run_module, "TERMINATE_GRACE_S", GRACE_S)


def no_check(device: str, *, cancel: threading.Event | None = None) -> None:
    """The check before the scan is not what these tests are about (and may not reach USB)."""


def real_worker(sink: RecordingSink) -> Worker:
    session = partial(run_session, scan=partial(run_scan, timeout_s=TIMEOUT_S), precheck=no_check)
    return Worker(sink, discover=lambda: ScanTarget(device=DEVICE), session=session)


def wait_for(sink: RecordingSink, name: str) -> None:
    deadline = time.monotonic() + WAIT_S
    while name not in sink.names:
        assert time.monotonic() < deadline, f"no {name!r} event; got {sink.names}"
        time.sleep(0.01)


@pytest.mark.parametrize(
    "spec",
    [{"hang": True}, {"exit_delay_s": 30}],
    ids=["scanning", "exit-path"],
)
def test_cancel_finishes_within_the_grace_period_plus_a_second(
    form: ScanForm, fake_scanimage: Callable[..., None], spec: dict[str, Any]
) -> None:
    fake_scanimage(pages=1, ignore_sigterm=True, **spec)
    sink = RecordingSink()
    worker = real_worker(sink)
    worker.scan(form)
    wait_for(sink, "page")

    asked = time.monotonic()
    worker.cancel()
    assert sink.finished.wait(WAIT_S)
    took = time.monotonic() - asked

    result = sink.value("finished")
    assert isinstance(result, SessionResult)
    assert result.cancelled
    assert took <= GRACE_S + SLACK_S, f"Cancel took {took:.2f} s"
    assert took >= GRACE_S * 0.8  # scanimage was given its grace, not killed at once


def test_the_grace_period_is_short_enough_for_cancel_to_feel_immediate() -> None:
    assert DEFAULT_GRACE_S <= 5.0
