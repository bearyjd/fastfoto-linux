"""Closing the bridge while a thread is still handing it an event (review round 2, item 1).

A reporting thread (the worker, or the disk check) that had passed the "closed" check could still be
inside ``signal.emit`` when the app deleted the bridge: a use after free, seen as a segmentation
fault under stress. The check and the emit now happen under one lock that ``shutdown`` also takes
to close the bridge, so after ``shutdown`` returns no thread is in an emit, and the bridge is not
deleted at all while the job's thread is still running.
"""

import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from tests.gui.qt import require_qt

require_qt()

import shiboken6

from fastfoto_linux.gui.form import ScanForm
from fastfoto_linux.gui.qt import app
from fastfoto_linux.gui.qt import bridge as bridge_module
from fastfoto_linux.gui.qt.bridge import Bridge
from fastfoto_linux.scanner import ScanTarget
from fastfoto_linux.session import SessionResult, Stage
from tests.cli.fakes import DEVICE
from tests.gui.qt.qt_helpers import wait_until

ROOT = Path(__file__).resolve().parents[3]
STRESS_ROUNDS = 300
STRESS_TIMEOUT = 30  # a hang or a crash fails one test (and is reported before pytest-timeout)
IN_FLIGHT_WAIT = 0.3  # how long shutdown is given to (wrongly) return while an emit is under way
HANDS_OFF_WAIT = 5.0


class BlockingSignal:
    """A signal whose ``emit`` does not return until it is released: a thread caught inside it."""

    def __init__(self) -> None:
        self.inside = threading.Event()
        self.release = threading.Event()
        self.emitted = 0

    def emit(self, *_: object) -> None:
        self.emitted += 1
        self.inside.set()
        self.release.wait(HANDS_OFF_WAIT)


def test_shutdown_does_not_return_while_a_thread_is_inside_an_emit(make_bridge: Any) -> None:
    bridge = make_bridge()
    signal = BlockingSignal()
    reporter = threading.Thread(target=bridge._emit, args=(signal, 1))
    reporter.start()
    assert signal.inside.wait(HANDS_OFF_WAIT)
    closed = threading.Event()

    def close() -> None:
        bridge.shutdown()
        closed.set()

    closer = threading.Thread(target=close)
    closer.start()
    try:
        returned_early = closed.wait(IN_FLIGHT_WAIT)
    finally:
        signal.release.set()
        reporter.join(HANDS_OFF_WAIT)
        closer.join(HANDS_OFF_WAIT)
    assert not returned_early, "shutdown returned while a thread was still inside signal.emit"
    assert closed.is_set()


def test_nothing_is_emitted_once_shutdown_has_returned(make_bridge: Any) -> None:
    bridge = make_bridge()
    signal = BlockingSignal()
    bridge.shutdown()
    bridge._emit(signal, 1)
    assert signal.emitted == 0


def test_a_report_after_the_bridge_is_closed_and_deleted_is_ignored(make_bridge: Any) -> None:
    bridge = make_bridge()
    bridge.shutdown()
    shiboken6.delete(bridge)
    bridge.on_page(1)  # a straggler of the job after the window is gone: no error, no crash


def test_threads_reporting_while_the_bridge_is_closed_and_deleted_do_not_crash() -> None:
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software"}
    try:
        done = subprocess.run(
            [sys.executable, "-m", "tests.gui.qt.emit_stress_app", str(STRESS_ROUNDS)],
            check=False,
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=STRESS_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"the stress run did not finish within {STRESS_TIMEOUT} s (a hang)")
    assert done.returncode == 0, f"exit {done.returncode}: {done.stderr[-800:]}"
    assert f"done {STRESS_ROUNDS}" in done.stdout


# -- the bridge is not deleted while the job's thread is alive ---------------------------------


def running_bridge(stop: threading.Event) -> Bridge:
    """A bridge whose scan holds (and ignores the cancel) until ``stop`` is set."""

    def session(request: Any, **hooks: Any) -> SessionResult:
        hooks["on_stage"](Stage.SCANNING)
        stop.wait(HANDS_OFF_WAIT * 4)
        return SessionResult()

    bridge = Bridge(
        remember=False,
        form=ScanForm(output_folder=str(Path.cwd())),
        discover=lambda: ScanTarget(device=DEVICE),
        session=session,
    )
    bridge.checkScanner()
    wait_until(lambda: bridge.canScan, "the scanner to be found")
    bridge.startScan()
    wait_until(lambda: bridge.canCancel, "the scan to hold")
    return bridge


@pytest.mark.usefixtures("kirigami")
def test_the_bridge_is_left_alone_while_the_job_is_still_running_after_the_wait(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, tmp_path: Path, qapp: Any
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(bridge_module, "SHUTDOWN_WAIT", 0.3)
    stop = threading.Event()
    bridge = running_bridge(stop)
    monkeypatch.setattr(bridge_module, "Bridge", lambda: bridge)
    try:
        with caplog.at_level(logging.DEBUG, logger=app.logger.name):
            assert app.main(run_loop=lambda: 0) == 0
        assert shiboken6.isValid(bridge), "the bridge was deleted under a job that is still running"
        ours = [r for r in caplog.records if r.name == app.logger.name]
        debug = [r for r in ours if r.levelno == logging.DEBUG]
        assert debug, caplog.records
    finally:
        stop.set()
        deadline = time.monotonic() + HANDS_OFF_WAIT
        while bridge.job_alive and time.monotonic() < deadline:
            time.sleep(0.01)
        app.destroy_now(bridge)


@pytest.mark.usefixtures("kirigami")
def test_a_window_that_could_not_be_loaded_closes_the_bridge_before_deleting_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, qapp: Any
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(app, "qml_main", lambda: Path("/nonexistent/Main.qml"))
    order: list[str] = []

    class Watched(Bridge):
        def __init__(self) -> None:
            super().__init__(remember=False)
            self.destroyed.connect(lambda *_: order.append("deleted"))

        def shutdown(self) -> None:
            order.append("closed")
            super().shutdown()

    monkeypatch.setattr(bridge_module, "Bridge", Watched)
    assert app.main(run_loop=lambda: 0) == 1
    assert order == ["closed", "deleted"]
