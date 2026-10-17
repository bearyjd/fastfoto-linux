"""The bridge in Documents mode: the mode, its form and results, a scan through the worker."""

from pathlib import Path
from typing import Any

import pytest

from tests.gui.qt import require_qt

require_qt()

from PySide6.QtTest import QSignalSpy

from fastfoto_linux.documents import DocumentSettingsError
from fastfoto_linux.gui.docform import DocumentForm
from fastfoto_linux.gui.doctools import NATIVE_OCR_HINT, DocumentTools
from fastfoto_linux.gui.prefs import load_document_form, load_mode
from fastfoto_linux.gui.qt.bridge import Bridge
from fastfoto_linux.gui.state import Mode
from fastfoto_linux.scanner import ScanTarget
from tests.cli.fakes import DEVICE
from tests.gui.doc_helpers import FakeBuild, ScriptedDocumentSession
from tests.gui.qt.qt_helpers import settle, wait_until

pytestmark = pytest.mark.usefixtures("ocrmypdf_comes_with_the_app")


@pytest.fixture
def make_doc_bridge(make_bridge: Any, out: Path):
    """A bridge in Documents mode with a scripted document session and a fake build."""

    def make(*, ocr: str | None = "/usr/bin/ocrmypdf", **options: Any) -> Any:
        session = options.pop("session", None) or ScriptedDocumentSession(out)
        build = options.pop("build", None) or FakeBuild(out)
        tools = DocumentTools(
            session=session, build=build, find_ocr=lambda: ocr, in_flatpak=lambda: False
        )
        options.setdefault("mode", Mode.DOCUMENTS)
        bridge = make_bridge(documents=tools, **options)
        bridge.test_session, bridge.test_build = session, build
        return bridge

    return make


def ready(bridge: Any) -> None:
    bridge.checkScanner()
    wait_until(lambda: bridge.canScan, "the scanner to be found")


def test_the_mode_is_photos_unless_the_bridge_is_started_in_documents(make_bridge: Any) -> None:
    assert make_bridge().mode == "photos"
    assert make_bridge(mode=Mode.DOCUMENTS).mode == "documents"


def test_the_mode_is_switched_from_qml_and_announced(make_bridge: Any) -> None:
    bridge = make_bridge()
    changed = QSignalSpy(bridge.changed)
    bridge.setMode("documents")
    assert bridge.mode == "documents"
    assert changed.count() >= 1
    bridge.setMode("photos")
    assert bridge.mode == "photos"


def test_a_mode_nobody_knows_changes_nothing_and_raises_nothing(make_bridge: Any) -> None:
    bridge = make_bridge()
    bridge.setMode("scans")
    assert bridge.mode == "photos"
    assert bridge.bannerKind == "error"  # the slot never raises into QML: it says so


def test_the_mode_cannot_be_switched_while_a_scan_runs(make_doc_bridge: Any) -> None:
    session = ScriptedDocumentSession(Path.cwd(), hold=True)
    bridge = make_doc_bridge(session=session)
    ready(bridge)
    bridge.startScan()
    wait_until(lambda: bridge.canCancel, "the scan to hold")
    bridge.setMode("photos")
    assert bridge.mode == "documents"
    session.release.set()
    wait_until(lambda: bridge.state == "done", "the scan to end")


def test_the_documents_form_is_set_field_by_field(make_doc_bridge: Any) -> None:
    bridge = make_doc_bridge()
    bridge.setDocumentField("name", "Lease")
    bridge.setDocumentField("dpi", 600)
    bridge.setDocumentField("both_sides", False)
    form = bridge.documents.form
    assert (form["name"], form["dpi"], form["both_sides"]) == ("Lease", 600, False)
    assert bridge.form["album"] == ""  # the photos form is not touched


def test_a_bad_field_is_an_error_of_the_page_not_a_crash(make_doc_bridge: Any) -> None:
    bridge = make_doc_bridge()
    bridge.setDocumentField("name", "///")
    assert "name" in bridge.errors
    assert not bridge.canScan
    bridge.setDocumentField("name", "Lease")
    assert "name" not in bridge.errors


def test_a_field_the_form_does_not_have_is_said_not_raised(make_doc_bridge: Any) -> None:
    bridge = make_doc_bridge()
    bridge.setDocumentField("album", "x")
    assert bridge.bannerKind == "error"


def test_the_choices_are_the_cli_ones(make_doc_bridge: Any) -> None:
    bridge = make_doc_bridge()
    assert list(bridge.documents.dpiChoices) == [200, 300, 600]
    assert list(bridge.documents.colourChoices) == ["colour", "grey", "bw"]


def test_searchable_text_follows_what_is_installed(make_doc_bridge: Any) -> None:
    found = make_doc_bridge()
    assert found.documents.ocrAvailable is True
    assert found.documents.ocrHint == ""
    assert found.documents.searchableChecked is True
    missing = make_doc_bridge(ocr=None)
    assert missing.documents.ocrAvailable is False
    assert missing.documents.ocrHint == NATIVE_OCR_HINT
    assert missing.documents.searchableChecked is False


def test_the_destination_is_the_pdf_to_come(make_doc_bridge: Any, out: Path) -> None:
    bridge = make_doc_bridge()
    assert bridge.destination == f"{out}/Document_####.pdf"


def test_a_document_scan_runs_through_the_worker_and_lists_the_pdf(
    make_doc_bridge: Any, out: Path
) -> None:
    bridge = make_doc_bridge()
    ready(bridge)
    bridge.startScan()
    wait_until(lambda: bridge.state == "done", "the document scan to finish")
    settle()
    documents = bridge.documents
    assert documents.count == 1
    assert documents.heading == "Documents (1)"
    assert bridge.bannerKind == "positive"
    assert bridge.photoCount == 0
    model = documents.items
    assert model.rowCount() == 1
    assert bridge.outputUrl == out.as_uri()
    request = bridge.test_session.requests[0]
    assert request.settings.output_root == out
    assert request.dpi == 300


def test_the_stage_texts_come_through_in_order(make_doc_bridge: Any, out: Path) -> None:
    session = ScriptedDocumentSession(out, hold=True)
    bridge = make_doc_bridge(session=session)
    seen: list[str] = []
    bridge.changed.connect(lambda: seen.append(bridge.progressText))
    ready(bridge)
    bridge.startScan()
    wait_until(lambda: session.holding.is_set() and "Scanning page 4" in seen, "scanning")
    session.release.set()
    wait_until(lambda: bridge.state == "done", "the scan to end")
    settle()
    distinct = [text for index, text in enumerate(seen) if text and text != seen[index - 1]]
    assert "Scanning page 4" in distinct
    assert distinct.index("Making the PDF…") < distinct.index("Making the PDF (page 1 of 3)")
    assert distinct.index("Making the PDF (page 3 of 3)") < distinct.index(
        "Adding searchable text…"
    )


def test_cancel_keeps_the_pages_and_process_them_now_makes_the_pdf(
    make_doc_bridge: Any, out: Path
) -> None:
    session = ScriptedDocumentSession(out, hold=True)
    bridge = make_doc_bridge(session=session)
    ready(bridge)
    bridge.setDocumentField("name", "Lease")
    bridge.startScan()
    wait_until(lambda: bridge.canCancel, "the scan to hold")
    bridge.cancel()
    wait_until(lambda: bridge.state == "cancelled", "the cancel")
    assert bridge.canProcessKept
    assert "3 pages were scanned before you cancelled" in bridge.keptHtml
    assert bridge.processKeptText == "Process them now"
    bridge.processKept()
    wait_until(lambda: bridge.state == "done", "the kept pages to be made into a PDF")
    assert bridge.documents.count == 1
    ((pages, settings),) = bridge.test_build.calls
    assert len(pages) == 3
    assert settings.name == "Lease"


def test_a_refusal_from_the_session_is_a_banner_and_the_scanner_stays_found(
    make_doc_bridge: Any, out: Path
) -> None:
    refusal = DocumentSettingsError("the output folder is gone")
    bridge = make_doc_bridge(session=ScriptedDocumentSession(out, raises=refusal))
    ready(bridge)
    bridge.startScan()
    wait_until(lambda: bridge.state == "failed", "the refusal")
    assert bridge.bannerKind == "error"
    assert bridge.bannerText == "The scan did not start: the output folder is gone."
    assert bridge.scannerOk


def test_each_mode_is_remembered_in_the_one_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, qapp: Any, out: Path
) -> None:
    config = tmp_path / "config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    tools = DocumentTools(
        session=ScriptedDocumentSession(out),
        build=FakeBuild(out),
        find_ocr=lambda: None,
        in_flatpak=lambda: False,
    )
    bridge = Bridge(discover=lambda: ScanTarget(device=DEVICE), documents=tools)
    try:
        bridge.setMode("documents")
        bridge.setField("output_folder", str(out))
        bridge.setDocumentField("name", "Lease")
        bridge.setDocumentField("colour", "bw")
        ready(bridge)
        bridge.startScan()
        wait_until(lambda: bridge.state == "done", "the scan to end")
    finally:
        bridge.shutdown()
    path = config / "fastfoto-linux" / "gui.json"
    assert load_mode(path) is Mode.DOCUMENTS
    assert load_document_form(path) == DocumentForm(name="Lease", colour="bw")
    again = Bridge(discover=lambda: ScanTarget(device=DEVICE), documents=tools)
    try:
        assert again.mode == "documents"
        assert again.documents.form["name"] == "Lease"
        assert again.form["output_folder"] == str(out)
    finally:
        again.shutdown()


def test_shutting_down_during_a_document_scan_cancels_and_waits(
    make_doc_bridge: Any, out: Path
) -> None:
    session = ScriptedDocumentSession(out, hold=True)
    bridge = make_doc_bridge(session=session)
    ready(bridge)
    bridge.startScan()
    wait_until(lambda: bridge.canCancel, "the scan to hold")
    bridge.shutdown()
    assert not bridge.job_alive
