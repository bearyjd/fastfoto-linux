"""Real-window review workflow with synthetic pages and recording worker jobs."""

from dataclasses import replace
from pathlib import Path

import pytest

from tests.gui.qt import require_qt

require_qt()

from PIL import Image
from PySide6.QtCore import Q_ARG, Q_RETURN_ARG, QMetaObject, Qt, QUrl
from PySide6.QtQml import QQmlExpression, qmlContext
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest

from fastfoto_linux.documents import DocumentResult, OcrOutcome, OcrStatus, PartResult
from fastfoto_linux.gui import reviewside
from fastfoto_linux.gui.state import Mode
from fastfoto_linux.session import DocumentRawReason, DocumentSessionResult, Stage
from tests.gui.doc_helpers import DocFakeWorker
from tests.gui.qt import test_qml_documents
from tests.gui.qt.qt_helpers import child, click, invoke, settle, wait_until
from tests.gui.review_helpers import draft

pytestmark = pytest.mark.usefixtures("kirigami")
open_window = test_qml_documents.open_window


@pytest.fixture
def review_window(make_bridge, open_window, out):
    raw = out / ".raw" / "synthetic"
    raw.mkdir(parents=True)
    source = draft(raw)
    pages = []
    for page in source.pages:
        path = raw / page.name
        Image.new("RGB", (100, 200), "white").save(path, dpi=(300, 300))
        info = path.stat()
        pages.append(replace(page, size=info.st_size, mtime_ns=info.st_mtime_ns, thumb=None))
    source = replace(source, pages=tuple(pages))
    bridge = make_bridge(mode=Mode.DOCUMENTS)
    worker = DocFakeWorker()
    worker.write_draft = lambda *args: worker.calls.append(("write", args))
    worker.analyse_folder = lambda *args: worker.calls.append(("analyse", args))
    worker.preview_page = lambda *args: worker.calls.append(("preview", args))
    bridge.controller._worker = worker
    window, warnings = open_window(bridge)
    bridge.controller.check_scanner()
    bridge.controller.on_scanner(None)
    bridge.controller.start_scan()
    wait_until(lambda: getattr(worker, "review", False), "review scan dispatch")
    bridge.controller.on_stage(Stage.PROCESSING)
    bridge.controller.on_finished(
        DocumentSessionResult(draft=source, raw_dir=raw, raw_reason=DocumentRawReason.REVIEW)
    )
    wait_until(lambda: child(window, "reviewGrid").property("count") == 3, "review page")
    settle()
    assert warnings == [], "initial review page"
    return window, bridge, worker, source, warnings


def saved_result(out: Path, source) -> DocumentSessionResult:
    outcome = OcrOutcome(OcrStatus.SKIPPED, "")
    parts = (
        PartResult(out / "Letters_0001.pdf", "Letters", 1, outcome),
        PartResult(out / "Receipts_0002.pdf", "Receipts", 2, outcome),
    )
    result = DocumentResult(pages_read=3, dropped=(), parts=parts)
    return DocumentSessionResult(document=result, raw_dir=source.raw_dir, draft=source)


def test_real_window_edits_save_two_parts_and_explicit_delete_offer(review_window, out, messages):
    window, bridge, worker, source, warnings = review_window
    bridge.review.toggle(2)
    bridge.review.rotate(3, 1)
    bridge.review.toggleSplit(3)
    assert bridge.review.setPartName(1, "Letters")
    assert bridge.review.setPartName(2, "Receipts")
    settle()
    assert len(bridge.review.parts) == 2
    click(child(window, "reviewSaveButton"))
    assert worker.names[-1] == "write"
    assert source.raw_dir.joinpath(source.pages[0].name).exists()
    bridge.controller.on_finished(saved_result(out, source))
    wait_until(lambda: bridge.state == "done", "saved PDFs")
    settle()
    assert bridge.review.canDeleteOriginals
    assert child(window, "deleteOriginalPagesButton").property("visible")
    assert child(window, "documentsList").property("count") == 2
    click(child(window, "deleteOriginalPagesButton"))
    dialog = child(window, "deleteOriginalPagesDialog")
    invoke(dialog, "reject")
    assert all((source.raw_dir / p.name).exists() for p in source.pages)
    click(child(window, "deleteOriginalPagesButton"))
    invoke(dialog, "accept")
    assert not any((source.raw_dir / p.name).exists() for p in source.pages)
    assert not bridge.review.canDeleteOriginals
    assert warnings == []
    assert messages == []


@pytest.mark.parametrize("cancelled", [False, True])
def test_failed_or_cancelled_save_returns_to_the_grid_with_edits(
    review_window, cancelled, messages
):
    window, bridge, _worker, _source, warnings = review_window
    bridge.review.rotate(3, 1)
    click(child(window, "reviewSaveButton"))
    if cancelled:
        bridge.controller.cancel()
    bridge.controller.on_finished(
        DocumentSessionResult(
            cancelled=cancelled, error=None if cancelled else OSError("synthetic full disk")
        )
    )
    wait_until(lambda: bridge.review.active, "review after unsuccessful Save")
    settle()
    assert bridge.review.items.get(2)["turns"] == 1
    assert not bridge.review.canDeleteOriginals
    assert child(window, "reviewGrid").property("count") == 3
    assert warnings == []
    assert messages == []


def test_preview_arrives_asynchronously_and_back_reopens_past_folder(review_window, messages):
    window, bridge, worker, source, warnings = review_window
    grid = child(window, "reviewGrid")
    invoke(grid, "forceActiveFocus")
    QTest.keyClick(window, Qt.Key.Key_Return)
    assert worker.names[-1] == "preview"
    preview = source.raw_dir / "previews" / "page-0001.jpg"
    preview.parent.mkdir()
    Image.new("RGB", (40, 60), "white").save(preview)
    bridge.controller.review.preview_ready((source, 1, preview, ""))
    settle()
    assert child(window, "reviewPreviewImage").property("source").toLocalFile() == str(preview)
    invoke(child(window, "reviewPreviewDialog"), "close")
    click(child(window, "reviewBackButton"))
    assert not bridge.review.active
    bridge.controller.on_scanner(None)
    bridge.review.openFolder(QUrl.fromLocalFile(str(source.raw_dir)))
    assert worker.names[-1] == "analyse"
    bridge.controller.on_finished(DocumentSessionResult(draft=source, raw_dir=source.raw_dir))
    wait_until(lambda: bridge.review.active, "past scan review")
    assert warnings == []
    assert messages == []


def test_window_close_commits_the_part_name_and_flushes_review(review_window, monkeypatch):
    window, bridge, _worker, _source, _warnings = review_window
    saved = []
    monkeypatch.setattr(reviewside, "save_draft", lambda *args: saved.append(args[0]))
    names = child(window, "reviewPartNames")
    row = QMetaObject.invokeMethod(names, "itemAt", Q_RETURN_ARG(QQuickItem), Q_ARG(int, 0))
    field = child(row, "reviewPartName")
    invoke(field, "forceActiveFocus")
    QTest.keyClick(window, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    for letter in "report":
        QTest.keyClick(window, Qt.Key(ord(letter.upper())))
    window.close()
    settle()
    assert saved
    assert saved[-1].part_names[1] == "report"
    assert not window.isVisible()
    assert bridge.review.parts[0]["name"] == "report"


def test_failed_flush_rejects_close_and_keeps_the_grid(review_window, monkeypatch):
    window, bridge, _worker, _source, _warnings = review_window

    def fail(*args):
        raise OSError("synthetic full disk")

    monkeypatch.setattr(reviewside, "save_draft", fail)
    bridge.review.rotate(3, 1)
    window.close()
    settle()
    assert window.isVisible()
    assert bridge.review.active
    assert bridge.bannerKind == "error"
    monkeypatch.setattr(reviewside, "save_draft", lambda *args: None)


def test_notifications_and_reopen_keep_one_review_page(review_window, messages):
    window, bridge, _worker, source, warnings = review_window

    def depth():
        return QQmlExpression(qmlContext(window), window, "pageStack.depth").evaluate()[0]

    assert depth() == 2
    for number in (1, 3, 1):
        bridge.review.focus(number)
        bridge.review.setFlaggedOnly(True)
        bridge.review.setFlaggedOnly(False)
    bridge.review.setPartName(1, "Letters")
    bridge.review.rotate(3, 1)
    settle()
    assert depth() == 2
    click(child(window, "reviewBackButton"))
    settle()
    assert depth() == 1
    bridge.controller.on_scanner(None)
    bridge.review.openFolder(QUrl.fromLocalFile(str(source.raw_dir)))
    bridge.controller.on_finished(DocumentSessionResult(draft=source, raw_dir=source.raw_dir))
    settle()
    assert depth() == 2
    assert warnings == []
    assert messages == []


def test_failed_ocr_save_has_no_original_deletion_offer(review_window, out, messages):
    window, bridge, _worker, source, warnings = review_window
    click(child(window, "reviewSaveButton"))
    result = saved_result(out, source)
    failed = replace(
        result.document.parts[0], ocr=OcrOutcome(OcrStatus.FAILED, "synthetic OCR failure")
    )
    result = replace(
        result, document=replace(result.document, parts=(failed, *result.document.parts[1:]))
    )
    bridge.controller.on_finished(result)
    settle()
    assert bridge.review.active
    assert not bridge.review.canDeleteOriginals
    assert not child(window, "deleteOriginalPagesButton").property("visible")
    assert all((source.raw_dir / p.name).exists() for p in source.pages)
    assert warnings == []
    assert messages == []
