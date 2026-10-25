"""The narrowest window (gridUnit * 40): headers wrap or elide, and the language list folds away."""

import threading
from pathlib import Path
from typing import Any

import pytest

from tests.gui.qt import require_qt

require_qt()

from PySide6.QtQuick import QQuickItem

from fastfoto_linux.documents import OcrCancelledError, OcrStatus, ocr_languages
from fastfoto_linux.documents.ocr_languages import Inventory, Language
from tests.gui.doc_helpers import ScriptedDocumentSession, clean_document
from tests.gui.qt import test_qml_documents, test_qml_languages
from tests.gui.qt.qt_helpers import child, click, settle, wait_until

pytestmark = pytest.mark.usefixtures("kirigami", "ocrmypdf_comes_with_the_app")
open_window = test_qml_documents.open_window
make_doc_bridge = test_qml_documents.make_doc_bridge


def narrow(window: Any) -> None:
    """Shrink to the window's minimum width."""
    window.setWidth(window.property("minimumWidth"))
    settle()


def overflowing(root: QQuickItem) -> list[str]:
    """Names of visible items below ``root`` that stick out of their parent's width."""
    found: list[str] = []
    for item in root.childItems():
        parent = item.parentItem()
        if (
            item.isVisible()
            and item.width() > 0
            and (item.x() < -1 or item.x() + item.width() > parent.width() + 1)
        ):
            found.append(item.objectName() or type(item).__name__)
        found += overflowing(item)
    return found


def fits(item: QQuickItem) -> bool:
    """The item and every ancestor lie within their parent's width."""
    while item.parentItem() is not None:
        if item.x() < -1 or item.x() + item.width() > item.parentItem().width() + 1:
            return False
        item = item.parentItem()
    return True


# -- the language picker ------------------------------------------------------------------------


def picker_parts(window: Any) -> tuple[Any, Any, Any, Any]:
    return (
        child(window, "docLanguagePicker"),
        child(window, "docLanguageToggle"),
        child(window, "docLanguageSearch"),
        child(window, "docLanguageScroll"),
    )


def test_the_language_picker_starts_collapsed_and_opens_with_its_toggle(
    make_doc_bridge: Any, open_window: Any
) -> None:
    window, warnings = open_window(make_doc_bridge())
    settle()
    picker, toggle, search, scroll = picker_parts(window)
    assert picker.property("expanded") is False
    assert not search.property("visible") and not scroll.property("visible")
    assert child(window, "docLanguageSummary").property("visible")
    assert toggle.property("visible")
    assert toggle.property("text") == "Show languages"
    click(toggle)
    settle()
    assert picker.property("expanded") is True
    assert search.property("visible") and scroll.property("visible")
    assert toggle.property("text") == "Hide languages"
    click(toggle)
    settle()
    assert picker.property("expanded") is False
    assert not search.property("visible") and not scroll.property("visible")
    assert warnings == []


def test_only_a_running_job_forces_the_picker_open_and_a_message_can_be_collapsed(
    monkeypatch: pytest.MonkeyPatch, make_doc_bridge: Any, open_window: Any
) -> None:
    inventory = Inventory(
        (Language("eng", "English", 100, installed=True), Language("spa", "Spanish", 200))
    )
    entered = threading.Event()

    def download(codes: tuple[str, ...], **options: Any) -> None:
        entered.set()
        assert options["cancel"].wait(5)
        raise OcrCancelledError("Cancelled")

    monkeypatch.setattr(ocr_languages, "discover_languages", lambda **_k: inventory)
    monkeypatch.setattr("fastfoto_linux.gui.qt.languages_view.download_languages", download)
    bridge = make_doc_bridge()
    wait_until(lambda: not bridge.documents.languages.busy, "languages")
    window, _ = open_window(bridge)
    settle()
    picker, toggle, search, scroll = picker_parts(window)
    assert picker.property("expanded") is False and toggle.property("enabled") is True
    bridge.documents.languages.setSelected("spa", True)
    click(child(window, "docDownloadLanguagesButton"))
    assert entered.wait(2)
    settle()
    assert search.property("visible") and scroll.property("visible")  # busy: forced open
    assert toggle.property("enabled") is False
    assert "working" in toggle.property("text")  # says why it is grey
    click(child(window, "docCancelLanguageDownloadButton"))
    wait_until(lambda: not bridge.documents.languages.busy, "cancel")
    settle()
    assert bridge.documents.languages.message
    assert toggle.property("enabled") is True  # a message alone does not lock it
    assert not search.property("visible") and not scroll.property("visible")
    click(toggle)
    settle()
    assert search.property("visible")
    click(toggle)
    settle()
    assert not search.property("visible")


def test_collapsing_moves_focus_from_the_hidden_search_field_to_the_toggle(
    make_doc_bridge: Any, open_window: Any
) -> None:
    window, _ = open_window(make_doc_bridge())
    settle()
    _, toggle, search, _ = picker_parts(window)
    click(toggle)
    settle()
    search.forceActiveFocus()
    settle()
    assert window.activeFocusItem() is search
    click(toggle)
    settle()
    assert window.activeFocusItem() is toggle


def test_collapsing_moves_focus_from_a_language_checkbox_to_the_toggle(
    monkeypatch: pytest.MonkeyPatch, make_doc_bridge: Any, open_window: Any
) -> None:
    inventory = Inventory((Language("eng", "English", 100, installed=True),))
    monkeypatch.setattr(ocr_languages, "discover_languages", lambda **_k: inventory)
    bridge = make_doc_bridge()
    wait_until(lambda: bridge.documents.languages.ready, "installed languages")
    window, _ = open_window(bridge)
    settle()
    _, toggle, _, _ = picker_parts(window)
    click(toggle)
    settle()
    box = test_qml_languages.language_box(window, "eng")
    box.forceActiveFocus()
    settle()
    assert window.activeFocusItem() is box
    click(toggle)
    settle()
    assert window.activeFocusItem() is toggle


# -- headers at the narrowest window --------------------------------------------------------------


def check_header(window: Any, heading: Any, flow: Any, warnings: list[str]) -> None:
    first = flow.childItems()[0]
    assert fits(heading) and fits(flow)
    heading.setProperty("text", "A very long heading " * 20)
    settle()
    assert heading.property("truncated") is True  # so the hover tooltip has a reason to show
    assert overflowing(flow) == []
    assert flow.height() >= first.height()
    assert warnings == []  # no binding or polish loops from the Flow in the ColumnLayout


def test_the_documents_header_and_rows_fit_the_narrowest_window(
    make_doc_bridge: Any, open_window: Any, out: Path
) -> None:
    session = ScriptedDocumentSession(out, result=clean_document(out, pages=3, ocr=OcrStatus.DONE))
    bridge = make_doc_bridge(session=session)
    window, warnings = open_window(bridge)
    test_qml_documents.ready(bridge)
    bridge.startScan()
    wait_until(lambda: bridge.state == "done", "the scan to end")
    narrow(window)
    assert fits(child(window, "documentsResults"))
    flow = child(window, "openDocumentsFolderButton").parentItem()
    check_header(window, child(window, "documentsHeading"), flow, warnings)
    row = test_qml_documents.in_row(window, "documentPages").parentItem().parentItem()
    assert overflowing(row) == []


def test_the_photos_header_wraps_its_actions_at_the_narrowest_window(
    make_doc_bridge: Any, open_window: Any
) -> None:
    bridge = make_doc_bridge(mode="photos")
    window, warnings = open_window(bridge)
    narrow(window)
    flow = child(window, "enhancedSwitch").parentItem()
    check_header(window, child(window, "photosHeading"), flow, warnings)
    assert fits(child(window, "photosHeading").parentItem())


def test_the_actions_wrap_onto_a_second_row_when_the_pane_is_too_narrow_for_one(
    make_doc_bridge: Any, open_window: Any
) -> None:
    window, _ = open_window(make_doc_bridge(mode="photos"))
    narrow(window)
    flow = child(window, "enhancedSwitch").parentItem()
    one_row = max(item.height() for item in flow.childItems())
    flow.setWidth(child(window, "openSavedPhotoEditButton").width() + 10)
    settle()
    assert flow.implicitHeight() > one_row * 1.5
