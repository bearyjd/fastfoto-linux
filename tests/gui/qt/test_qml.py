"""The QML window, loaded for real (offscreen) and driven through the bridge."""

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.gui.qt import require_qt

require_qt()


from PySide6.QtCore import Q_ARG, Q_RETURN_ARG, QMetaObject, QObject
from PySide6.QtQuick import QQuickItem

from fastfoto_linux.gui.form import ScanForm
from fastfoto_linux.gui.qt.app import create_engine
from fastfoto_linux.scanner import ScanError
from fastfoto_linux.session import RawReason, SessionResult
from tests.gui.helpers import ScriptedSession
from tests.gui.qt.qt_helpers import child, click, invoke, settle, wait_until

pytestmark = pytest.mark.usefixtures("kirigami")


@pytest.fixture
def open_window(messages: list[str]) -> Iterator[Callable[[Any], tuple[Any, list[str]]]]:
    opened: list[tuple[Any, Any]] = []

    def open_(bridge: Any) -> tuple[Any, list[str]]:
        engine, warnings = create_engine(bridge)
        assert engine.rootObjects(), f"the window did not load: {warnings}"
        window = engine.rootObjects()[0]
        opened.append((engine, window))
        return window, warnings

    yield open_
    for engine, window in opened:
        window.close()
        window.deleteLater()
        engine.deleteLater()
    settle()


def ready(bridge: Any) -> None:
    bridge.checkScanner()
    wait_until(lambda: bridge.canScan, "the scanner to be found")


def test_the_window_loads_with_no_warnings_through_every_state(
    make_bridge: Any, open_window: Any, messages: list[str], out: Path
) -> None:
    session = ScriptedSession(out, hold=True)
    bridge = make_bridge(session=session)
    window, warnings = open_window(bridge)
    ready(bridge)
    bridge.setField("album", "Family Trips")
    bridge.setField("date", "soon")  # a form error shows
    bridge.setField("date", "1975-06")
    bridge.startScan()
    wait_until(lambda: bridge.canCancel, "the scan to hold")
    bridge.cancel()
    wait_until(lambda: bridge.state == "cancelled", "the cancel")
    settle()
    bridge.processKept()
    wait_until(lambda: bridge.state == "done", "the kept pages to be processed")
    invoke(child(window, "enhancedSwitch"), "toggle")
    session.hold = False
    session.result = SessionResult(
        error=ScanError("scanimage timed out"),
        raw_dir=out / ".raw" / "s",
        raw_reason=RawReason.SCAN_ERROR,
    )
    bridge.startScan()
    wait_until(lambda: bridge.state == "failed", "the failure")
    settle()
    bridge.checkScanner()
    settle()
    assert warnings == []
    assert messages == []


def test_scan_is_disabled_until_the_form_is_valid_and_a_scanner_is_found(
    make_bridge: Any, open_window: Any
) -> None:
    bridge = make_bridge()
    window, _ = open_window(bridge)
    scan = child(window, "scanButton")
    assert scan.property("enabled") is False
    ready(bridge)
    settle()
    assert scan.property("enabled") is True
    bridge.setField("date", "soon")
    settle()
    assert scan.property("enabled") is False


def test_cancel_is_enabled_only_while_scanning(
    make_bridge: Any, open_window: Any, out: Path
) -> None:
    session = ScriptedSession(out, hold=True)
    bridge = make_bridge(session=session)
    window, _ = open_window(bridge)
    cancel = child(window, "cancelButton")
    ready(bridge)
    settle()
    assert cancel.property("enabled") is False
    bridge.startScan()
    wait_until(lambda: cancel.property("enabled") is True, "Cancel to enable")
    session.release.set()
    wait_until(lambda: bridge.state == "done", "the scan to finish")
    settle()
    assert cancel.property("enabled") is False


def test_an_empty_results_area_shows_a_placeholder_until_photos_arrive(
    make_bridge: Any, open_window: Any
) -> None:
    bridge = make_bridge()
    window, _ = open_window(bridge)
    placeholder = child(window, "emptyPlaceholder")
    grid = child(window, "photosGrid")
    assert placeholder.property("visible") is True
    assert grid.property("count") == 0
    ready(bridge)
    bridge.startScan()
    wait_until(lambda: bridge.state == "done", "the scan to finish")
    settle()
    assert placeholder.property("visible") is False
    assert grid.property("count") == 3


def test_the_progress_label_follows_the_scan(make_bridge: Any, open_window: Any, out: Path) -> None:
    session = ScriptedSession(out, hold=True)
    bridge = make_bridge(session=session)
    window, _ = open_window(bridge)
    label = child(window, "progressLabel")
    ready(bridge)
    bridge.startScan()
    wait_until(lambda: str(label.property("text")).startswith("Scanning page"), "the label")
    session.release.set()
    wait_until(lambda: bridge.state == "done", "the scan to finish")


def test_a_failure_shows_an_error_banner_with_where_the_raw_pages_are(
    make_bridge: Any, open_window: Any, out: Path
) -> None:
    raw = out / ".raw" / "stamp"
    failed = SessionResult(
        error=ScanError("scanimage timed out"), raw_dir=raw, raw_reason=RawReason.SCAN_ERROR
    )
    bridge = make_bridge(session=ScriptedSession(out, photos=0, result=failed))
    window, _ = open_window(bridge)
    banner = child(window, "errorBanner")
    assert banner.property("visible") is False
    ready(bridge)
    bridge.startScan()
    wait_until(lambda: bridge.state == "failed", "the failure")
    settle()
    assert banner.property("visible") is True
    assert "scanimage timed out" in banner.property("text")
    assert str(raw) in banner.property("text")


def test_a_cancelled_scan_offers_to_process_the_pages_kept(
    make_bridge: Any, open_window: Any, out: Path
) -> None:
    bridge = make_bridge(session=ScriptedSession(out, hold=True))
    window, _ = open_window(bridge)
    kept = child(window, "keptBanner")
    process = child(window, "processKeptButton")
    assert kept.property("visible") is False
    ready(bridge)
    bridge.startScan()
    wait_until(lambda: bridge.canCancel, "the scan to hold")
    bridge.cancel()
    wait_until(lambda: bridge.state == "cancelled", "the cancel")
    settle()
    assert kept.property("visible") is True
    assert "6 pages were scanned before you cancelled" in kept.property("text")
    assert process.property("enabled") is True
    click(process)
    wait_until(lambda: bridge.state == "done", "the kept pages to be processed")
    settle()
    assert kept.property("visible") is False
    assert child(window, "photosGrid").property("count") == 3


def test_closing_the_window_while_scanning_asks_to_cancel_first(
    make_bridge: Any, open_window: Any, out: Path
) -> None:
    bridge = make_bridge(session=ScriptedSession(out, hold=True))
    window, _ = open_window(bridge)
    ready(bridge)
    bridge.startScan()
    wait_until(lambda: bridge.canCancel, "the scan to hold")
    window.close()
    settle()
    assert window.property("visible") is True
    dialog = child(window, "cancelDialog")
    wait_until(lambda: dialog.property("visible") is True, "the question")
    assert bridge.state == "scanning"
    invoke(dialog, "accept")
    wait_until(lambda: window.property("visible") is False, "the window to close")
    assert bridge.state == "cancelled"


def test_the_originals_and_enhanced_copies_can_be_switched(
    make_bridge: Any, open_window: Any
) -> None:
    bridge = make_bridge()
    window, _ = open_window(bridge)
    switch = child(window, "enhancedSwitch")
    ready(bridge)
    bridge.startScan()
    wait_until(lambda: bridge.state == "done", "the scan to finish")
    settle()
    assert switch.property("checked") is False
    invoke(switch, "toggle")
    settle()
    assert switch.property("checked") is True


def test_check_again_runs_a_new_check(make_bridge: Any, open_window: Any) -> None:
    from fastfoto_linux.scanner import ScannerNotFoundError

    state = {"found": False}

    def discover() -> Any:
        if not state["found"]:
            raise ScannerNotFoundError("no FF-680W found on USB")
        from fastfoto_linux.scanner import ScanTarget

        return ScanTarget(device="epsonds:libusb:001:004")

    bridge = make_bridge(discover=discover)
    window, _ = open_window(bridge)
    again = child(window, "checkAgainButton")
    bridge.checkScanner()
    wait_until(lambda: bridge.state == "no_scanner", "no scanner")
    settle()
    assert again.property("enabled") is True
    state["found"] = True
    click(again)
    wait_until(lambda: bridge.state == "ready", "the scanner to be found")


# -- Review round 1 --------------------------------------------------------------------------------


def test_yes_to_the_close_question_closes_the_window_even_if_the_scan_ended_meanwhile(
    make_bridge: Any, open_window: Any, out: Path
) -> None:
    session = ScriptedSession(out, hold=True)
    bridge = make_bridge(session=session)
    window, _ = open_window(bridge)
    ready(bridge)
    bridge.startScan()
    wait_until(lambda: bridge.canCancel, "the scan to hold")
    window.close()
    dialog = child(window, "cancelDialog")
    wait_until(lambda: dialog.property("visible") is True, "the question")
    session.release.set()  # the scan finishes while the question is on screen
    wait_until(lambda: bridge.state == "done", "the scan to finish")
    invoke(dialog, "accept")
    wait_until(lambda: window.property("visible") is False, "the window to close")


def test_a_failed_scan_with_kept_pages_shows_one_banner_and_no_process_button(
    make_bridge: Any, open_window: Any, out: Path
) -> None:
    raw = out / ".raw" / "stamp"
    failed = SessionResult(
        error=ScanError("scanimage timed out"),
        raw_dir=raw,
        raw_reason=RawReason.SCAN_ERROR,
        kept_pages=(raw / "page-0001.png",),
    )
    bridge = make_bridge(session=ScriptedSession(out, photos=0, result=failed))
    window, _ = open_window(bridge)
    ready(bridge)
    bridge.startScan()
    wait_until(lambda: bridge.state == "failed", "the failure")
    settle()
    shown = {
        name: child(window, name).property("visible")
        for name in ("errorBanner", "keptBanner", "resultBanner", "processKeptButton")
    }
    assert shown == {
        "errorBanner": True,
        "keptBanner": False,
        "resultBanner": False,
        "processKeptButton": False,
    }
    assert "ffscan process" in child(window, "errorBanner").property("text")


def test_the_offer_to_process_survives_check_again_in_the_window(
    make_bridge: Any, open_window: Any, out: Path
) -> None:
    bridge = make_bridge(session=ScriptedSession(out, hold=True))
    window, _ = open_window(bridge)
    ready(bridge)
    bridge.startScan()
    wait_until(lambda: bridge.canCancel, "the scan to hold")
    bridge.cancel()
    wait_until(lambda: bridge.state == "cancelled", "the cancel")
    click(child(window, "checkAgainButton"))
    wait_until(lambda: bridge.state == "ready", "the check")
    settle()
    assert child(window, "processKeptButton").property("visible") is True
    assert "before you cancelled" in child(window, "keptBanner").property("text")
    assert child(window, "resultBanner").property("visible") is False


def test_the_scan_button_has_its_reason_beside_it(make_bridge: Any, open_window: Any) -> None:
    bridge = make_bridge(form=ScanForm())
    window, _ = open_window(bridge)
    reason = child(window, "scanBlocker")
    bridge.checkScanner()
    wait_until(lambda: bridge.state == "ready", "the scanner to be found")  # but no folder yet
    settle()
    assert child(window, "scanButton").property("enabled") is False
    assert reason.property("visible") is True
    assert reason.property("text") == "Choose the folder the photos are saved in."
    bridge.setField("output_folder", str(Path.cwd()))
    settle()
    assert reason.property("visible") is False


def test_the_red_eye_warning_is_text_on_the_page_not_a_tooltip(
    make_bridge: Any, open_window: Any
) -> None:
    window, _ = open_window(make_bridge())
    warning = child(window, "redeyeWarning")
    settle()
    assert warning.property("visible") is True
    assert "1 fix in 6" in warning.property("text")


def test_the_results_grid_can_be_walked_with_the_keyboard_and_shows_where_it_is(
    make_bridge: Any, open_window: Any
) -> None:
    window, _ = open_window(make_bridge())
    grid = child(window, "photosGrid")
    assert grid.property("keyNavigationEnabled") is True
    assert grid.property("highlightFollowsCurrentItem") is True
    assert grid.property("highlight") is not None


def named_items(root: Any, name: str) -> list[Any]:
    """Every item below ``root`` called ``name``, found through the visual tree."""
    found = [root] if root.objectName() == name else []
    for item in root.childItems():
        found += named_items(item, name)
    return found


def cells_of(grid: Any) -> list[Any]:
    """The grid's delegate items (they are not QObject children of the grid)."""
    count = grid.property("count")
    cells = [
        QMetaObject.invokeMethod(grid, "itemAtIndex", Q_RETURN_ARG(QQuickItem), Q_ARG(int, row))
        for row in range(count)
    ]
    return [cell for cell in cells if cell is not None]


def test_every_photo_cell_is_the_same_size_with_or_without_a_back(
    make_bridge: Any, open_window: Any
) -> None:
    bridge = make_bridge()  # the scripted scan gives the first photo a back and the others none
    window, _ = open_window(bridge)
    ready(bridge)
    bridge.startScan()
    wait_until(lambda: bridge.state == "done", "the scan to finish")
    settle()

    grid = child(window, "photosGrid")

    def laid_out() -> bool:
        cells = cells_of(grid)
        frames = [f for cell in cells for f in named_items(cell, "frontFrame")]
        return len(frames) == 3 and all(frame.property("width") > 0 for frame in frames)

    wait_until(laid_out, "the three cells")
    cells = cells_of(grid)
    frames = [f for cell in cells for f in named_items(cell, "frontFrame")]
    assert len({(f.property("width"), f.property("height")) for f in frames}) == 1
    images = [i for cell in cells for i in named_items(cell, "frontImage")]
    assert {image.property("width") for image in images} == {frames[0].property("width")}
    assert {image.property("height") for image in images} == {frames[0].property("height")}


def rendered_text(banner: QObject) -> str:
    """What the banner's text area shows, as plain text (markup that was interpreted is gone)."""
    for item in banner.findChildren(QObject):
        if "TextEdit" in item.metaObject().className():
            length = item.property("length")
            return str(
                QMetaObject.invokeMethod(
                    item, "getText", Q_RETURN_ARG(str), Q_ARG(int, 0), Q_ARG(int, length)
                )
            )
    raise AssertionError("the banner has no text area")


def test_markup_in_a_message_is_shown_as_it_is_not_interpreted(
    make_bridge: Any, open_window: Any, out: Path
) -> None:
    hostile = "<b>bold</b> and <i>italic</i>"
    failed = SessionResult(error=ScanError(hostile))
    bridge = make_bridge(session=ScriptedSession(out, photos=0, result=failed))
    window, _ = open_window(bridge)
    ready(bridge)
    bridge.startScan()
    wait_until(lambda: bridge.state == "failed", "the failure")
    settle()
    assert "<b>bold</b> and <i>italic</i>" in rendered_text(child(window, "errorBanner"))
