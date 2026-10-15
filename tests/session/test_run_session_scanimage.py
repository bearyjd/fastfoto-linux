"""``run_session`` over the real runner and a fake ``scanimage`` executable (a real subprocess)."""

import threading
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any

import pytest

from fastfoto_linux.pipeline.process import ProcessResult
from fastfoto_linux.scanner import run_scan
from fastfoto_linux.session import RawPolicy, RawReason, Stage, run_session
from tests._fake_scanimage import fake_env, install
from tests.session.conftest import STAMP, Events, kept_names, make_request, raw_leftovers

CANCEL_DELAY_S = 0.3
SCAN_TIMEOUT_S = 3.0  # a scan that is not stopped gives up soon instead of hanging the suite


@pytest.fixture
def fake_scanimage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """Make the next scan run the fake ``scanimage`` told to behave as ``spec`` says."""

    def configure(**spec: Any) -> None:
        for name, value in fake_env(install(tmp_path / "bin"), **spec).items():
            monkeypatch.setenv(name, value)

    return configure


def real_scan() -> Callable[..., Any]:
    return partial(run_scan, timeout_s=SCAN_TIMEOUT_S)


def must_not_run(*args: Any, **kwargs: Any) -> ProcessResult:
    raise AssertionError("a cancelled scan must not be processed")


def test_a_cancel_from_another_thread_stops_scanimage_and_keeps_the_pages(
    out, tmp_path, fake_scanimage
) -> None:
    marker = tmp_path / "sigterm-marker"
    fake_scanimage(pages=1, hang=True, sigterm_marker=str(marker))
    cancel = threading.Event()
    canceller = threading.Timer(CANCEL_DELAY_S, cancel.set)
    events = Events()

    def on_page(number: int) -> None:
        events.pages.append(number)
        canceller.start()  # the first page is down: now somebody presses Cancel

    try:
        session = run_session(
            make_request(out, duplex=False, policy=RawPolicy.DISCARD),
            scan=real_scan(),
            process=must_not_run,
            cancel=cancel,
            on_page=on_page,
            on_stage=events.stages.append,
        )
    finally:
        canceller.cancel()
    assert marker.read_text() == "terminated"  # scanimage was stopped, not left scanning
    assert session.cancelled is True
    assert session.error is None
    assert session.process is None
    assert session.pages_scanned == 1
    assert session.raw_reason is RawReason.CANCELLED
    assert session.raw_dir == out / ".raw" / STAMP
    assert kept_names(session.raw_dir) == ["page-0001.png"]
    assert events.pages == [1]
    assert events.stages == [Stage.SCANNING, Stage.DONE]


def test_a_cancel_that_is_already_set_scans_nothing(out, tmp_path, fake_scanimage) -> None:
    marker = tmp_path / "started"
    fake_scanimage(pages=1, record_to=str(marker))
    cancel = threading.Event()
    cancel.set()
    session = run_session(
        make_request(out, duplex=False),
        scan=real_scan(),
        process=must_not_run,
        cancel=cancel,
    )
    assert not marker.exists()  # scanimage was never started
    assert session.cancelled is True
    assert (session.raw_dir, session.error, session.process) == (None, None, None)
    assert raw_leftovers(out) == []


def test_the_pages_the_runner_announces_are_the_pages_processed(out, fake_scanimage) -> None:
    fake_scanimage(pages=3)
    seen: list[tuple[str, ...]] = []

    def process(pages, settings, **options) -> ProcessResult:
        seen.append(tuple(p.name for p in pages))
        return ProcessResult()

    events = Events()
    session = run_session(
        make_request(out, duplex=False), scan=real_scan(), process=process, **events.callbacks()
    )
    assert events.pages == [1, 2, 3]
    assert seen == [("page-0001.png", "page-0002.png", "page-0003.png")]
    assert session.pages_scanned == 3
    assert session.ok is True
    assert raw_leftovers(out) == []
    assert events.stages == [Stage.SCANNING, Stage.PROCESSING, Stage.DONE]
