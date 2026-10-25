"""Drive actual language checkboxes, search, and cancellable explicit downloads in QML."""

import threading
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from tests.gui.qt import require_qt

require_qt()

from PySide6.QtCore import QMetaObject

from fastfoto_linux.documents import OcrCancelledError, ocr_languages
from fastfoto_linux.documents.ocr_languages import Inventory, Language
from tests.gui.doc_helpers import ScriptedDocumentSession
from tests.gui.qt import test_qml_documents
from tests.gui.qt.qt_helpers import child, click, settle, wait_until

pytestmark = pytest.mark.usefixtures("kirigami", "ocrmypdf_comes_with_the_app")
open_window = test_qml_documents.open_window
make_doc_bridge = test_qml_documents.make_doc_bridge


def expand(window: Any) -> None:
    """Open the folded-away language list, as a user does."""
    click(child(window, "docLanguageToggle"))
    settle()


def language_box(window: Any, code: str) -> Any:
    def find(item: Any) -> Any:
        if item.objectName() == f"docLanguageBox_{code}":
            return item
        for candidate in item.childItems():
            found = find(candidate)
            if found is not None:
                return found
        return None

    box = find(child(window, "docLanguageList"))
    assert box is not None, f"No checkbox for {code}"
    return box


def test_checkboxes_and_search_preserve_order_and_custom_installed_codes(
    monkeypatch: pytest.MonkeyPatch, make_doc_bridge: Any, open_window: Any
) -> None:
    inventory = Inventory(
        (
            Language("eng", "English", 100, installed=True),
            Language("spa", "Spanish", 200, installed=True),
            Language("custom", "Custom local language", 0, installed=True),
        )
    )
    monkeypatch.setattr(ocr_languages, "discover_languages", lambda **_k: inventory)
    bridge = make_doc_bridge()
    wait_until(lambda: bridge.documents.languages.ready, "installed languages")
    bridge.setDocumentField("langs", "spa+custom+eng")
    window, warnings = open_window(bridge)
    settle()
    expand(window)
    assert language_box(window, "eng").property("checked")
    search = child(window, "docLanguageSearch")
    search.setProperty("text", "SPAN")
    assert QMetaObject.invokeMethod(search, "textEdited")
    settle()
    assert bridge.documents.form["langs"] == "spa+custom+eng"
    assert child(window, "docLanguageList").property("count") == 1
    assert language_box(window, "spa").property("checked")
    click(language_box(window, "spa"))
    settle()
    assert bridge.documents.form["langs"] == "custom+eng"
    click(language_box(window, "spa"))
    settle()
    assert bridge.documents.form["langs"] == "custom+eng+spa"
    assert warnings == []


def test_explicit_download_shows_orientation_size_progress_cancel_and_retry(
    monkeypatch: pytest.MonkeyPatch, make_doc_bridge: Any, open_window: Any
) -> None:
    inventory = Inventory(
        (Language("eng", "English", 100, installed=True), Language("spa", "Spanish", 200)),
        orientation=Language("osd", "Orientation", 400),
    )
    calls: list[tuple[str, ...]] = []
    entered = threading.Event()

    def download(codes: tuple[str, ...], **options: Any) -> None:
        nonlocal inventory
        calls.append(tuple(codes))
        options["progress"]("spa", 100, 200)
        entered.set()
        if len(calls) == 1:
            assert options["cancel"].wait(5)
            raise OcrCancelledError("Cancelled")
        inventory = Inventory(
            tuple(replace(row, installed=True) for row in inventory.languages),
            orientation=Language("osd", "Orientation", 400, installed=True),
        )

    monkeypatch.setattr(ocr_languages, "discover_languages", lambda **_k: inventory)
    monkeypatch.setattr("fastfoto_linux.gui.qt.languages_view.download_languages", download)
    bridge = make_doc_bridge()
    wait_until(lambda: not bridge.documents.languages.busy, "languages")
    window, warnings = open_window(bridge)
    settle()
    expand(window)
    click(language_box(window, "spa"))
    settle()
    summary = child(window, "docLanguageDownloadSummary").property("text")
    assert "600 B" in summary and "orientation" in summary
    assert calls == []
    click(child(window, "docDownloadLanguagesButton"))
    assert entered.wait(2)
    wait_until(lambda: bridge.documents.languages.progress == 0.5, "download progress")
    assert calls == [("spa", "osd")]
    assert child(window, "docNameField").property("enabled") is False
    assert child(window, "docLanguageSearch").property("enabled") is False
    assert "100 B / 200 B" in child(window, "docLanguageProgress").property("text")
    bridge.setDocumentField("langs", "eng")
    assert bridge.documents.form["langs"] == "eng+spa"
    click(child(window, "docCancelLanguageDownloadButton"))
    wait_until(lambda: not bridge.documents.languages.busy, "cancel")
    assert "cancel" in child(window, "docLanguageMessage").property("text").lower()
    click(child(window, "docDownloadLanguagesButton"))
    wait_until(lambda: bridge.documents.languages.ready, "retry completes")
    assert calls == [("spa", "osd"), ("spa", "osd")]
    assert bridge.documents.form["langs"] == "eng+spa"
    assert not child(window, "docDownloadLanguagesButton").property("enabled")
    assert warnings == []


def test_missing_language_blocks_scan_but_searchable_off_can_scan(
    monkeypatch: pytest.MonkeyPatch, make_doc_bridge: Any, open_window: Any, out: Path
) -> None:
    inventory = Inventory((Language("eng", "English", 100),))
    monkeypatch.setattr(ocr_languages, "discover_languages", lambda **_k: inventory)
    session = ScriptedDocumentSession(out)
    bridge = make_doc_bridge(session=session)
    wait_until(lambda: not bridge.documents.languages.busy, "languages")
    window, _warnings = open_window(bridge)
    bridge.checkScanner()
    wait_until(lambda: bridge.scannerOk, "scanner")
    assert not bridge.canScan
    assert "Download selected languages" in child(window, "docLanguageScanHint").property("text")
    bridge.startScan()
    assert session.requests == []
    assert "eng" in bridge.bannerText
    bridge.setDocumentField("searchable", False)
    assert bridge.canScan
    bridge.startScan()
    wait_until(lambda: bridge.state == "done", "OCR-off scan")
    assert len(session.requests) == 1
