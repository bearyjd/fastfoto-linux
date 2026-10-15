"""Review round 2 at the Qt layer: refused actions, text that keeps its spacing, shutdown."""

import threading
import time
from pathlib import Path
from typing import Any

import pytest

from tests.gui.qt import require_qt

require_qt()

from PySide6.QtTest import QSignalSpy

from fastfoto_linux.gui.form import ScanForm
from fastfoto_linux.gui.qt import bridge as bridge_module
from fastfoto_linux.gui.qt.bridge import Bridge, rich_text
from fastfoto_linux.scanner import ScanTarget
from fastfoto_linux.session import SessionResult, Stage
from tests.cli.fakes import DEVICE
from tests.gui.helpers import ScriptedSession
from tests.gui.qt.qt_helpers import wait_until


def ready(bridge: Any) -> None:
    bridge.checkScanner()
    wait_until(lambda: bridge.canScan, "the scanner to be found")


def test_a_refused_cancel_changes_nothing_and_shows_no_error(make_bridge: Any) -> None:
    bridge = make_bridge()
    ready(bridge)
    spy = QSignalSpy(bridge.changed)
    bridge.cancel()
    assert bridge.state == "ready"
    assert bridge.bannerKind == ""
    assert bridge.canScan
    assert spy.count() >= 1  # the page is told, so a button that looked enabled is redrawn


def test_a_stray_start_during_a_scan_is_ignored_and_the_scan_goes_on(
    make_bridge: Any, out: Path
) -> None:
    session = ScriptedSession(out, hold=True)
    bridge = make_bridge(session=session)
    ready(bridge)
    bridge.startScan()
    wait_until(lambda: bridge.canCancel, "the scan to hold")
    bridge.startScan()
    bridge.checkScanner()
    bridge.processKept()
    assert bridge.state == "scanning"
    assert bridge.bannerKind == ""
    session.release.set()
    wait_until(lambda: bridge.state == "done", "the scan, which was not cancelled, to finish")
    assert bridge.photoCount == 3


def test_text_keeps_its_spacing_and_is_still_escaped() -> None:
    assert rich_text("a  b\n  c") == '<span style="white-space:pre-wrap">a  b\n  c</span>'
    assert rich_text("<b>x</b> & y") == (
        '<span style="white-space:pre-wrap">&lt;b&gt;x&lt;/b&gt; &amp; y</span>'
    )
    assert rich_text("") == ""


# -- shutdown ----------------------------------------------------------------------------------


def stubborn_bridge(stop: threading.Event, seen: list[bool]) -> Bridge:
    """A bridge whose scan ignores the cancel until ``stop`` is set."""

    def session(request: Any, **hooks: Any) -> SessionResult:
        hooks["on_stage"](Stage.SCANNING)
        stop.wait(20)
        seen.append(hooks["cancel"].is_set())
        return SessionResult()

    bridge = Bridge(
        remember=False,
        form=ScanForm(output_folder=str(Path.cwd())),
        discover=lambda: ScanTarget(device=DEVICE),
        session=session,
    )
    ready(bridge)
    bridge.startScan()
    wait_until(lambda: bridge.canCancel, "the scan to hold")
    return bridge


def test_shutdown_waits_a_bounded_time_once_and_a_second_call_returns_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bridge_module, "SHUTDOWN_WAIT", 0.4)
    stop, seen = threading.Event(), []
    bridge = stubborn_bridge(stop, seen)
    begun = time.monotonic()
    bridge.shutdown()
    first = time.monotonic() - begun
    begun = time.monotonic()
    bridge.shutdown()
    second = time.monotonic() - begun
    stop.set()
    assert 0.35 <= first < 3
    assert second < 0.1


def test_an_abort_cancels_and_ends_the_wait_in_a_moment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bridge_module, "SHUTDOWN_WAIT", 30)
    stop, seen = threading.Event(), []
    bridge = stubborn_bridge(stop, seen)
    threading.Timer(0.3, bridge.abort).start()
    begun = time.monotonic()
    bridge.shutdown()
    assert time.monotonic() - begun < 4
    stop.set()
    wait_until(lambda: seen, "the scan to notice")
    assert seen == [True]  # the cancel was set before the app went away
