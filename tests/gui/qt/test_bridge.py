import threading
from pathlib import Path
from typing import Any

import pytest

from tests.gui.qt import require_qt

require_qt()

from PySide6.QtCore import QUrl
from PySide6.QtTest import QSignalSpy

from fastfoto_linux.gui.form import ScanForm
from fastfoto_linux.gui.state import InvalidTransitionError
from fastfoto_linux.scanner import ScannerNotFoundError
from fastfoto_linux.session import SessionResult, Stage
from tests.gui.helpers import ScriptedSession, written
from tests.gui.qt.qt_helpers import wait_until

SINK_CALLS = [
    ("on_scanner", (None,)),
    ("on_stage", (Stage.PROCESSING,)),
    ("on_page", (4,)),
    ("on_photo", (written(Path("/srv/demo/FastFoto"), 1),)),
    ("on_finished", (SessionResult(),)),
    ("on_error", (RuntimeError("boom"),)),
]


@pytest.mark.parametrize(("name", "args"), SINK_CALLS)
def test_events_from_a_worker_thread_run_on_the_gui_thread(
    make_bridge: Any, name: str, args: tuple[Any, ...]
) -> None:
    bridge = make_bridge()
    calls: list[tuple[int, tuple[Any, ...]]] = []
    setattr(bridge.controller, name, lambda *a: calls.append((threading.get_ident(), a)))
    sender = threading.Thread(target=getattr(bridge, name), args=args)
    sender.start()
    sender.join()
    assert calls == []  # queued: nothing runs until the GUI thread's event loop does
    wait_until(lambda: calls, f"{name} to arrive")
    arrived_on, arrived_with = calls[0]
    assert arrived_on == threading.get_ident() != sender.ident
    assert arrived_with == args


def test_a_check_finds_the_scanner(make_bridge: Any) -> None:
    bridge = make_bridge()
    assert bridge.state == "idle"
    assert not bridge.canScan
    bridge.checkScanner()
    assert bridge.busy
    wait_until(lambda: bridge.state == "ready", "the scanner to be found")
    assert bridge.canScan
    assert not bridge.canCancel
    assert not bridge.busy


def test_no_scanner_is_reported_with_the_reason(make_bridge: Any) -> None:
    def missing() -> Any:
        raise ScannerNotFoundError("no FF-680W found on USB; check the cable")

    bridge = make_bridge(discover=missing)
    bridge.checkScanner()
    wait_until(lambda: bridge.state == "no_scanner", "the check to fail")
    assert "check the cable" in bridge.scannerText
    assert not bridge.canScan
    assert bridge.canCheck


def test_a_scan_fills_the_photos_model_as_photos_arrive(make_bridge: Any, out: Any) -> None:
    session = ScriptedSession(out, photos=3)
    bridge = make_bridge(session=session)
    bridge.checkScanner()
    wait_until(lambda: bridge.canScan, "ready")
    bridge.startScan()
    wait_until(lambda: bridge.state == "done", "the scan to finish")
    assert bridge.photoCount == 3
    assert bridge.photos.rowCount() == 3
    assert bridge.bannerKind == "positive"
    assert "3 photos saved" in bridge.bannerText
    assert bridge.outputUrl.endswith("Family%20Trips")
    assert session.requests[0].settings.output_root == out


def test_properties_notify_through_one_changed_signal(make_bridge: Any) -> None:
    bridge = make_bridge()
    spy = QSignalSpy(bridge.changed)
    bridge.checkScanner()
    wait_until(lambda: bridge.state == "ready", "ready")
    assert spy.count() >= 2


def test_cancel_stops_a_held_scan_and_offers_the_pages(make_bridge: Any, out: Any) -> None:
    session = ScriptedSession(out, hold=True)
    bridge = make_bridge(session=session)
    bridge.checkScanner()
    wait_until(lambda: bridge.canScan, "ready")
    bridge.startScan()
    wait_until(lambda: bridge.canCancel, "the scan to be cancellable")
    assert bridge.progressText.startswith("Scanning page")
    bridge.cancel()
    wait_until(lambda: bridge.state == "cancelled", "the cancel to finish")
    assert not bridge.canCancel
    assert bridge.canProcessKept
    assert "before you cancelled" in bridge.bannerText
    bridge.processKept()
    wait_until(lambda: bridge.state == "done", "the kept pages to be processed")
    assert bridge.photoCount == 3
    assert not bridge.canProcessKept


def test_set_field_updates_the_form_and_its_errors(make_bridge: Any) -> None:
    bridge = make_bridge()
    bridge.setField("date", "soon")
    assert bridge.form["date"] == "soon"
    assert "date" in bridge.errors
    bridge.setField("date", "1975")
    assert bridge.errors == {}
    bridge.setField("dpi", 300)
    assert bridge.form["dpi"] == 300
    bridge.setField("redeye", True)
    assert bridge.form["redeye"] is True
    assert "Rome" not in bridge.destination
    bridge.setField("album", "Rome")
    assert "Rome" in bridge.destination


def test_the_form_starts_from_the_remembered_one(make_bridge: Any, out: Any) -> None:
    bridge = make_bridge(form=ScanForm(output_folder=str(out), album="Rome", dpi=300))
    assert bridge.form["album"] == "Rome"
    assert bridge.form["dpi"] == 300


def test_choosing_a_folder_sets_the_output_folder(make_bridge: Any, tmp_path: Any) -> None:
    bridge = make_bridge()
    other = tmp_path / "other folder"
    other.mkdir()
    bridge.setOutputFolderUrl(QUrl.fromLocalFile(str(other)))
    assert bridge.form["output_folder"] == str(other)
    assert bridge.errors == {}


def test_closing_when_idle_is_allowed_at_once(make_bridge: Any) -> None:
    assert make_bridge().requestClose() is True


def test_closing_while_scanning_cancels_first_and_then_says_so(make_bridge: Any, out: Any) -> None:
    bridge = make_bridge(session=ScriptedSession(out, hold=True))
    bridge.checkScanner()
    wait_until(lambda: bridge.canScan, "ready")
    bridge.startScan()
    wait_until(lambda: bridge.canCancel, "the scan to be cancellable")
    ready = QSignalSpy(bridge.closeReady)
    assert bridge.requestClose() is False
    wait_until(lambda: ready.count() == 1, "closeReady")
    assert bridge.state == "cancelled"


@pytest.mark.parametrize("name", ["startScan", "cancel", "processKept"])
def test_actions_that_are_not_allowed_raise_instead_of_doing_nothing(
    make_bridge: Any, name: str
) -> None:
    with pytest.raises(InvalidTransitionError):
        getattr(make_bridge(), name)()
