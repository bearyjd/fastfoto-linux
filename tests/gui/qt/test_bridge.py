import shutil
import threading
from pathlib import Path
from typing import Any

import pytest

from tests.gui.qt import require_qt

require_qt()

import shiboken6
from PySide6.QtCore import QCoreApplication, QUrl
from PySide6.QtTest import QSignalSpy

from fastfoto_linux.gui.form import ScanForm
from fastfoto_linux.scanner import ScanError, ScannerNotFoundError
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
def test_a_slot_never_raises_a_blocked_action_changes_nothing(make_bridge: Any, name: str) -> None:
    bridge = make_bridge()
    getattr(bridge, name)()  # QML would swallow a traceback to stderr and the page would look dead
    assert bridge.state == "idle"  # (round 2: a refused action is not a failure)
    assert bridge.bannerKind == ""
    assert bridge.canCheck


def test_an_unexpected_error_while_scanning_ends_in_failed_not_in_a_stuck_page(
    make_bridge: Any, out: Any
) -> None:
    session = ScriptedSession(out, hold=True)
    bridge = make_bridge(session=session)
    bridge.checkScanner()
    wait_until(lambda: bridge.canScan, "ready")
    bridge.startScan()
    wait_until(lambda: bridge.canCancel, "the scan to hold")
    bridge.on_photo(object())  # not a WrittenFiles: the controller raises while handling it
    wait_until(lambda: bridge.state == "failed", "the page to fail")
    assert bridge.bannerKind == "error"
    assert not bridge.running
    wait_until(lambda: not bridge._worker.busy, "the job to be told to stop")
    wait_until(lambda: bridge.canCheck, "the page to be usable")
    for _ in range(20):  # the late result of the stopped job is dropped, not applied
        QCoreApplication.processEvents()
    assert bridge.state == "failed"


def test_a_folder_that_vanished_is_reported_when_scan_is_pressed(
    make_bridge: Any, out: Any
) -> None:
    bridge = make_bridge()
    bridge.checkScanner()
    wait_until(lambda: bridge.canScan, "ready")
    shutil.rmtree(out)
    bridge.startScan()
    assert bridge.state == "ready"
    assert "output_folder" in bridge.errors
    assert bridge.bannerKind == "error"
    assert "does not exist" in bridge.bannerText
    assert not bridge.canScan


def test_the_disk_is_checked_when_the_user_is_done_editing_the_folder(
    make_bridge: Any, tmp_path: Any
) -> None:
    bridge = make_bridge()
    bridge.setField("output_folder", str(tmp_path / "nowhere"))
    assert bridge.errors == {}
    bridge.checkDisk()
    assert "does not exist" in bridge.errors["output_folder"]


def test_choosing_a_missing_folder_is_reported_at_once(make_bridge: Any, tmp_path: Any) -> None:
    bridge = make_bridge()
    bridge.setOutputFolderUrl(QUrl.fromLocalFile(str(tmp_path / "nowhere")))
    assert "does not exist" in bridge.errors["output_folder"]


def test_the_scan_button_says_why_it_is_disabled(make_bridge: Any, out: Any) -> None:
    bridge = make_bridge(form=ScanForm())
    assert bridge.whyNotScan
    bridge.setField("output_folder", str(out))
    bridge.checkScanner()
    wait_until(lambda: bridge.canScan, "ready")
    assert bridge.whyNotScan == ""


def test_open_folder_never_gets_a_relative_url(
    make_bridge: Any, out: Any, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "photos").mkdir()
    monkeypatch.chdir(tmp_path)
    bridge = make_bridge()
    assert bridge.outputUrl.startswith("file:///")
    bridge.setField("output_folder", "photos")
    assert "output_folder" in bridge.errors
    assert bridge.outputUrl == ""


def test_the_kept_pages_offer_survives_checking_the_scanner_again(
    make_bridge: Any, out: Any
) -> None:
    bridge = make_bridge(session=ScriptedSession(out, hold=True))
    bridge.checkScanner()
    wait_until(lambda: bridge.canScan, "ready")
    bridge.startScan()
    wait_until(lambda: bridge.canCancel, "the scan to hold")
    bridge.cancel()
    wait_until(lambda: bridge.state == "cancelled", "the cancel")
    assert bridge.canProcessKept
    bridge.checkScanner()
    wait_until(lambda: bridge.state == "ready", "the second check")
    assert bridge.canProcessKept
    assert "before you cancelled" in bridge.keptHtml
    bridge.processKept()
    wait_until(lambda: bridge.state == "done", "the pages to be processed")
    assert bridge.photoCount == 3


def test_text_from_the_user_or_the_disk_reaches_the_banners_escaped(
    make_bridge: Any, out: Any
) -> None:
    hostile = '<b>bold</b> <img src="file:///etc/passwd"> & more'
    failed = SessionResult(error=ScanError(hostile))
    bridge = make_bridge(session=ScriptedSession(out, photos=0, result=failed))
    bridge.checkScanner()
    wait_until(lambda: bridge.canScan, "ready")
    bridge.startScan()
    wait_until(lambda: bridge.state == "failed", "the failure")
    assert hostile in bridge.bannerText  # the plain text is untouched
    html = bridge.bannerHtml
    assert "<b>" not in html
    assert "<img" not in html
    assert "&lt;b&gt;bold&lt;/b&gt;" in html
    assert "&amp; more" in html
    assert html.startswith("<")  # Qt takes it as rich text, so the entities are shown as text


def test_a_stopped_bridge_drops_what_a_late_worker_sends(make_bridge: Any) -> None:
    bridge = make_bridge()
    bridge.shutdown()
    errors: list[BaseException] = []

    def send() -> None:
        try:
            bridge.on_photo(written(Path("/srv/demo"), 1))
            bridge.on_finished(SessionResult())
        except BaseException as error:
            errors.append(error)

    sender = threading.Thread(target=send)
    sender.start()
    sender.join()
    for _ in range(10):
        QCoreApplication.processEvents()
    assert errors == []
    assert bridge.photoCount == 0


def test_a_worker_that_outlives_the_bridge_object_cannot_crash_the_thread(
    make_bridge: Any,
) -> None:
    bridge = make_bridge()
    shiboken6.delete(bridge)
    errors: list[BaseException] = []

    def send() -> None:
        try:
            bridge.on_page(1)
            bridge.on_error(RuntimeError("late"))
        except BaseException as error:
            errors.append(error)

    sender = threading.Thread(target=send)
    sender.start()
    sender.join()
    assert errors == []
