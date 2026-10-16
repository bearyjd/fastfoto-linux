"""The window in Documents mode, loaded for real (offscreen): no warnings, the right controls."""

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.gui.qt import require_qt

require_qt()


from PySide6.QtCore import QObject, Slot
from PySide6.QtGui import QDesktopServices

from fastfoto_linux.documents import OcrStatus
from fastfoto_linux.gui.doctools import NATIVE_OCR_HINT, DocumentTools
from fastfoto_linux.gui.qt.app import create_engine
from fastfoto_linux.gui.state import Mode
from fastfoto_linux.scanner import ScanError
from tests.gui.doc_helpers import (
    FakeBuild,
    ScriptedDocumentSession,
    clean_document,
    stopped_document,
)
from tests.gui.qt.qt_helpers import child, click, settle, wait_until

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


@pytest.fixture
def make_doc_bridge(make_bridge: Any, out: Path):
    def make(*, ocr: str | None = "/usr/bin/ocrmypdf", **options: Any) -> Any:
        session = options.pop("session", None) or ScriptedDocumentSession(out)
        tools = DocumentTools(
            session=session,
            build=options.pop("build", None) or FakeBuild(out),
            find_ocr=lambda: ocr,
            in_flatpak=lambda: False,
        )
        options["mode"] = Mode(options.get("mode", "documents"))
        return make_bridge(documents=tools, **options)

    return make


def ready(bridge: Any) -> None:
    bridge.checkScanner()
    wait_until(lambda: bridge.canScan, "the scanner to be found")


def shown(window: Any, name: str) -> bool:
    return bool(child(window, name).property("visible"))


# -- the window loads and stays quiet --------------------------------------------------------


def test_the_window_loads_in_documents_mode_with_no_warnings_through_every_state(
    make_doc_bridge: Any, open_window: Any, messages: list[str], out: Path
) -> None:
    session = ScriptedDocumentSession(out, hold=True)
    bridge = make_doc_bridge(session=session)
    _, warnings = open_window(bridge)
    ready(bridge)
    bridge.setDocumentField("name", "///")  # a form error shows
    bridge.setDocumentField("langs", "!")
    bridge.setDocumentField("name", "Lease")
    bridge.setDocumentField("langs", "eng+deu")
    bridge.startScan()
    wait_until(lambda: bridge.canCancel, "the scan to hold")
    bridge.cancel()
    wait_until(lambda: bridge.state == "cancelled", "the cancel")
    settle()
    bridge.processKept()
    wait_until(lambda: bridge.state == "done", "the kept pages to be made into a PDF")
    settle()
    session.hold = False
    session.result = stopped_document(out / ".raw" / "s", ScanError("the paper jammed"))
    bridge.startScan()
    wait_until(lambda: bridge.state == "failed", "the failure")
    settle()
    session.result = clean_document(out, ocr=OcrStatus.FAILED, detail="exit 6", dropped=(2, 4))
    bridge.startScan()
    wait_until(lambda: bridge.state == "done", "the scan with a warning")
    settle()
    bridge.setMode("photos")
    settle()
    bridge.setMode("documents")
    settle()
    assert warnings == []
    assert messages == []


def test_a_window_that_starts_in_photos_mode_switches_with_no_warnings(
    make_doc_bridge: Any, open_window: Any, messages: list[str]
) -> None:
    bridge = make_doc_bridge(mode="photos")
    _, warnings = open_window(bridge)
    for mode in ("documents", "photos", "documents"):
        bridge.setMode(mode)
        settle()
    assert warnings == []
    assert messages == []


# -- the mode switch -------------------------------------------------------------------------


def test_the_switch_shows_the_mode_and_changes_it(make_doc_bridge: Any, open_window: Any) -> None:
    bridge = make_doc_bridge(mode="photos")
    window, _ = open_window(bridge)
    assert shown(window, "photosForm") and not shown(window, "documentsForm")
    assert child(window, "photosModeButton").property("checked") is True
    click(child(window, "documentsModeButton"))
    settle()
    assert bridge.mode == "documents"
    assert shown(window, "documentsForm") and not shown(window, "photosForm")
    assert child(window, "documentsModeButton").property("checked") is True
    click(child(window, "photosModeButton"))
    settle()
    assert bridge.mode == "photos"


def test_the_switch_cannot_be_used_while_a_scan_runs(
    make_doc_bridge: Any, open_window: Any, out: Path
) -> None:
    session = ScriptedDocumentSession(out, hold=True)
    bridge = make_doc_bridge(session=session)
    window, _ = open_window(bridge)
    ready(bridge)
    bridge.startScan()
    wait_until(lambda: bridge.canCancel, "the scan to hold")
    settle()
    assert child(window, "photosModeButton").property("enabled") is False
    assert child(window, "documentsModeButton").property("enabled") is False
    session.release.set()
    wait_until(lambda: bridge.state == "done", "the scan to end")
    settle()
    assert child(window, "photosModeButton").property("enabled") is True


def test_each_mode_shows_its_own_results_area(make_doc_bridge: Any, open_window: Any) -> None:
    bridge = make_doc_bridge()
    window, _ = open_window(bridge)
    assert shown(window, "documentsList") and not shown(window, "photosGrid")
    assert shown(window, "documentsPlaceholder")
    bridge.setMode("photos")
    settle()
    assert shown(window, "photosGrid") and not shown(window, "documentsList")


# -- the form --------------------------------------------------------------------------------


def test_the_form_shows_the_documents_settings_and_none_of_the_photo_ones(
    make_doc_bridge: Any, open_window: Any
) -> None:
    bridge = make_doc_bridge()
    window, _ = open_window(bridge)
    for name in (
        "docFolderField",
        "docNameField",
        "docColourBox",
        "docDpiBox",
        "docBothSidesBox",
        "docKeepBlankBox",
        "docSearchableBox",
        "docLangsField",
    ):
        assert shown(window, name), name
    for name in ("albumField", "dateField", "restoreBox", "feedBox"):
        assert not shown(window, name), name


def test_the_controls_show_the_form_and_the_form_follows_the_controls(
    make_doc_bridge: Any, open_window: Any
) -> None:
    bridge = make_doc_bridge()
    window, _ = open_window(bridge)
    bridge.setDocumentField("name", "Lease")
    bridge.setDocumentField("dpi", 600)
    bridge.setDocumentField("colour", "grey")
    bridge.setDocumentField("both_sides", False)
    bridge.setDocumentField("keep_blank", True)
    settle()
    assert child(window, "docNameField").property("text") == "Lease"
    assert child(window, "docDpiBox").property("currentValue") == 600
    assert child(window, "docColourBox").property("currentValue") == "grey"
    assert child(window, "docBothSidesBox").property("checked") is False
    assert child(window, "docKeepBlankBox").property("checked") is True
    click(child(window, "docBothSidesBox"))
    settle()
    assert bridge.documents.form["both_sides"] is True


def test_the_defaults_are_those_of_the_command_line(make_doc_bridge: Any, open_window: Any) -> None:
    bridge = make_doc_bridge()
    window, _ = open_window(bridge)
    assert child(window, "docColourBox").property("currentValue") == "colour"
    assert child(window, "docDpiBox").property("currentValue") == 300
    assert child(window, "docBothSidesBox").property("checked") is True
    assert child(window, "docKeepBlankBox").property("checked") is False
    assert child(window, "docLangsField").property("text") == "eng"


def test_a_bad_field_shows_its_message_under_it(make_doc_bridge: Any, open_window: Any) -> None:
    bridge = make_doc_bridge()
    window, _ = open_window(bridge)
    assert not shown(window, "docNameError")
    bridge.setDocumentField("name", "///")
    bridge.setDocumentField("langs", "!")
    settle()
    assert "file name" in child(window, "docNameError").property("text")
    assert "Tesseract" in child(window, "docLangsError").property("text")
    assert shown(window, "docNameError") and shown(window, "docLangsError")


def test_the_destination_shows_the_pdf_to_come(
    make_doc_bridge: Any, open_window: Any, out: Path
) -> None:
    bridge = make_doc_bridge()
    window, _ = open_window(bridge)
    assert child(window, "docDestinationLabel").property("text") == (
        f"Saved as {out}/Document_####.pdf"
    )


def test_searchable_text_can_be_chosen_when_ocrmypdf_is_installed(
    make_doc_bridge: Any, open_window: Any
) -> None:
    bridge = make_doc_bridge()
    window, _ = open_window(bridge)
    box = child(window, "docSearchableBox")
    assert box.property("enabled") is True
    assert box.property("checked") is True
    assert not shown(window, "docOcrHint")
    click(box)
    settle()
    assert bridge.documents.form["searchable"] is False


def test_searchable_text_is_off_and_explained_when_it_is_not_installed(
    make_doc_bridge: Any, open_window: Any
) -> None:
    bridge = make_doc_bridge(ocr=None)
    window, _ = open_window(bridge)
    box = child(window, "docSearchableBox")
    assert box.property("enabled") is False
    assert box.property("checked") is False
    assert shown(window, "docOcrHint")
    assert child(window, "docOcrHint").property("text") == NATIVE_OCR_HINT


def test_the_form_cannot_be_edited_while_a_scan_runs(
    make_doc_bridge: Any, open_window: Any, out: Path
) -> None:
    session = ScriptedDocumentSession(out, hold=True)
    bridge = make_doc_bridge(session=session)
    window, _ = open_window(bridge)
    ready(bridge)
    bridge.startScan()
    wait_until(lambda: bridge.canCancel, "the scan to hold")
    settle()
    for name in ("docNameField", "docColourBox", "docDpiBox", "docBothSidesBox", "docLangsField"):
        assert child(window, name).property("enabled") is False, name
    session.release.set()
    wait_until(lambda: bridge.state == "done", "the scan to end")


# -- the results -----------------------------------------------------------------------------


def test_a_finished_scan_lists_the_pdf_with_its_details(
    make_doc_bridge: Any, open_window: Any, out: Path
) -> None:
    session = ScriptedDocumentSession(
        out, result=clean_document(out, pages=3, dropped=(2, 4), ocr=OcrStatus.DONE)
    )
    bridge = make_doc_bridge(session=session)
    window, _ = open_window(bridge)
    ready(bridge)
    bridge.startScan()
    wait_until(lambda: bridge.state == "done", "the scan to end")
    settle()
    assert child(window, "documentsList").property("count") == 1
    assert not shown(window, "documentsPlaceholder")
    assert child(window, "documentsHeading").property("text") == "Documents (1)"
    assert child(window, "documentFileName").property("text") == "Document_0001.pdf"
    assert child(window, "documentPages").property("text") == "3 pages"
    assert child(window, "documentDropped").property("text") == "Blank pages left out: 2, 4"
    assert child(window, "documentSearchable").property("text") == "Searchable text: yes"
    assert child(window, "openDocumentButton").property("enabled") is True


def test_a_warning_of_the_ocr_is_shown_with_the_pdf(
    make_doc_bridge: Any, open_window: Any, out: Path
) -> None:
    result = clean_document(out, ocr=OcrStatus.FAILED, detail="exit 6")
    bridge = make_doc_bridge(session=ScriptedDocumentSession(out, result=result))
    window, _ = open_window(bridge)
    ready(bridge)
    bridge.startScan()
    wait_until(lambda: bridge.state == "done", "the scan to end")
    settle()
    text = child(window, "documentSearchable").property("text")
    assert text.startswith("Searchable text could not be added (exit 6)")
    assert not shown(window, "documentDropped")


def test_open_gives_the_file_to_the_desktop(
    make_doc_bridge: Any, open_window: Any, out: Path
) -> None:
    class Recorder(QObject):
        def __init__(self) -> None:
            super().__init__()
            self.urls: list[str] = []

        @Slot("QUrl")
        def opened(self, url: Any) -> None:
            self.urls.append(url.toString())

    recorder = Recorder()
    QDesktopServices.setUrlHandler("file", recorder, "opened")
    try:
        bridge = make_doc_bridge()
        window, _ = open_window(bridge)
        ready(bridge)
        bridge.startScan()
        wait_until(lambda: bridge.state == "done", "the scan to end")
        settle()
        click(child(window, "openDocumentButton"))
        settle()
    finally:
        QDesktopServices.unsetUrlHandler("file")
    assert recorder.urls == [f"{out.as_uri()}/Document_0001.pdf"]


def test_the_open_folder_button_opens_the_output_folder_in_documents_mode_too(
    make_doc_bridge: Any, open_window: Any, out: Path
) -> None:
    bridge = make_doc_bridge()
    window, _ = open_window(bridge)
    button = child(window, "openFolderButton")
    assert button.property("enabled") is True
    assert bridge.outputUrl == out.as_uri()


def test_the_banner_and_the_offer_to_process_kept_pages_work_for_documents(
    make_doc_bridge: Any, open_window: Any, out: Path
) -> None:
    session = ScriptedDocumentSession(out, hold=True)
    bridge = make_doc_bridge(session=session)
    window, _ = open_window(bridge)
    ready(bridge)
    bridge.startScan()
    wait_until(lambda: bridge.canCancel, "the scan to hold")
    bridge.cancel()
    wait_until(lambda: bridge.state == "cancelled", "the cancel")
    settle()
    assert child(window, "processKeptButton").property("visible") is True
    assert child(window, "processKeptButton").property("text") == "Process them now"
    click(child(window, "processKeptButton"))
    wait_until(lambda: bridge.state == "done", "the kept pages to be made into a PDF")
    settle()
    assert child(window, "documentsList").property("count") == 1


def test_the_page_is_titled_for_the_mode(make_doc_bridge: Any, open_window: Any) -> None:
    bridge = make_doc_bridge()
    window, _ = open_window(bridge)
    page = child(window, "scanPage")
    assert page.property("title") == "Scan documents"
    bridge.setMode("photos")
    settle()
    assert page.property("title") == "Scan photos"
