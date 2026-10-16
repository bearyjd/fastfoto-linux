"""Closing the window during a Cancel that scanimage ignores (review round 2, item 4).

A user Cancel gives scanimage ``TERMINATE_GRACE_S`` to stop the scanner cleanly, then SIGKILLs it.
The app's wait at shutdown used to be exactly as long, so it could give up just before the SIGKILL
and leave an orphan scanimage holding the scanner. The wait is now the grace plus a margin: the
SIGKILL always comes first.
"""

import contextlib
import os
import signal
import subprocess
import threading
from functools import partial
from pathlib import Path
from typing import Any

import pytest

from tests.gui.qt import require_qt

require_qt()

from fastfoto_linux.gui.form import ScanForm
from fastfoto_linux.gui.qt import bridge as bridge_module
from fastfoto_linux.gui.qt.bridge import Bridge
from fastfoto_linux.scanner import ScanTarget, run_scan
from fastfoto_linux.scanner import run as run_module
from fastfoto_linux.session import run_session
from tests._fake_scanimage import fake_env, install
from tests.cli.fakes import DEVICE
from tests.gui.qt.qt_helpers import wait_until

# What the app really uses, read when this module is imported (before any test patches them).
DEFAULT_GRACE_S = run_module.TERMINATE_GRACE_S
DEFAULT_WAIT_S = bridge_module.SHUTDOWN_WAIT
MIN_MARGIN_S = 3.0  # the SIGKILL, the reaping and the settling of the pages come after the grace
GRACE_S = 1.0  # the grace while the end-to-end test runs
TIMEOUT_S = 20.0  # a scan that is never stopped gives up here instead of hanging the suite


def test_the_shutdown_wait_is_the_cancel_grace_plus_a_margin_of_at_least_3_seconds() -> None:
    assert bridge_module.SHUTDOWN_MARGIN_S >= MIN_MARGIN_S
    assert DEFAULT_WAIT_S >= DEFAULT_GRACE_S + bridge_module.SHUTDOWN_MARGIN_S


def test_the_shutdown_wait_follows_the_grace_it_is_derived_from() -> None:
    assert DEFAULT_WAIT_S == DEFAULT_GRACE_S + bridge_module.SHUTDOWN_MARGIN_S


class RecordingPopen:
    def __init__(self) -> None:
        self.procs: list[subprocess.Popen[bytes]] = []

    def __call__(self, argv: tuple[str, ...], **kwargs: Any) -> "subprocess.Popen[bytes]":
        proc = subprocess.Popen(argv, **kwargs)
        self.procs.append(proc)
        return proc


def no_check(device: str, *, cancel: threading.Event | None = None) -> None:
    """The check before the scan is not what this test is about (and may not reach USB)."""


def test_no_scanimage_outlives_the_shutdown_of_an_app_whose_cancel_it_ignores(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, qapp: Any
) -> None:
    monkeypatch.setattr(run_module, "TERMINATE_GRACE_S", GRACE_S)
    monkeypatch.setattr(bridge_module, "SHUTDOWN_WAIT", GRACE_S + bridge_module.SHUTDOWN_MARGIN_S)
    for name, value in fake_env(
        install(tmp_path / "bin"), pages=1, hang=True, ignore_sigterm=True
    ).items():
        monkeypatch.setenv(name, value)  # SIGTERM is ignored once the first page is out
    out = tmp_path / "out"
    out.mkdir()
    popen, first_page = RecordingPopen(), threading.Event()

    def scan(job: Any, **options: Any) -> Any:
        progress = options.pop("on_progress")
        options["on_progress"] = lambda page: (first_page.set(), progress(page))
        return run_scan(job, popen=popen, timeout_s=TIMEOUT_S, **options)

    bridge = Bridge(
        remember=False,
        form=ScanForm(output_folder=str(out)),
        discover=lambda: ScanTarget(device=DEVICE),
        session=partial(run_session, scan=scan, precheck=no_check),
    )
    try:
        bridge.checkScanner()
        wait_until(lambda: bridge.canScan, "the scanner to be found")
        bridge.startScan()
        wait_until(first_page.is_set, "the first page")

        bridge.shutdown()  # cancels the job and waits for it

        assert popen.procs, "scanimage was never started"
        assert all(proc.poll() is not None for proc in popen.procs), "scanimage outlived the app"
    finally:
        for proc in popen.procs:  # the fake runs in its own session: nothing else would stop it
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)
