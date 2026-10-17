"""Making the PDF of kept pages: searchable text is not required, and a full disk is a result."""

import errno
from pathlib import Path
from typing import Any

import pytest

from fastfoto_linux.documents import OcrMode
from fastfoto_linux.documents.errors import OutputFolderMissingError
from fastfoto_linux.gui.docform import DocumentForm
from fastfoto_linux.gui.docreport import document_error_banner, offers_kept
from fastfoto_linux.gui.worker import Worker
from tests.gui.doc_helpers import DocRecordingSink, FakeBuild, ScriptedDocumentSession
from tests.gui.test_worker_documents import WAIT, finish, scan, worker_for


def cancelled_run(
    out: Path, build: Any, *, ocr: bool = True
) -> tuple[Worker, DocRecordingSink, Any]:
    """A worker that has scanned and been cancelled; returns it, its sink and the kept result."""
    session = ScriptedDocumentSession(out, hold=True)
    sink = DocRecordingSink()
    worker = worker_for(sink, session, build)
    scan(worker, out, DocumentForm(name="Lease"), ocr=ocr)
    assert session.holding.wait(WAIT)
    worker.cancel()
    finish(sink, worker)
    kept = sink.value("finished")
    sink.finished.clear()
    sink.events.clear()
    return worker, sink, kept


def test_searchable_text_that_was_required_at_the_scan_is_not_when_the_pages_are_made(
    out: Path,
) -> None:
    build = FakeBuild(out)
    worker, sink, kept = cancelled_run(out, build, ocr=True)
    worker.process_kept(kept)
    finish(sink, worker)
    ((_, settings),) = build.calls
    assert settings.ocr is OcrMode.AUTO  # the tool may be gone now: a plain PDF beats none


def test_pages_scanned_without_searchable_text_are_made_without_it(out: Path) -> None:
    build = FakeBuild(out, ocr=False)
    worker, sink, kept = cancelled_run(out, build, ocr=False)
    worker.process_kept(kept)
    finish(sink, worker)
    ((_, settings),) = build.calls
    assert settings.ocr is OcrMode.OFF


@pytest.mark.parametrize(
    ("crash", "banner_start"),
    [
        (
            OSError(errno.ENOSPC, "No space left on device", "/out/.Lease_0001.pdf.ab12.tmp"),
            "No PDF was made. The disk is full.",
        ),
        (
            PermissionError(errno.EACCES, "Permission denied", "/out/.Lease_0001.pdf.ab12.tmp"),
            "No PDF was made. The folder cannot be written to (permission denied).",
        ),
        (
            OSError(errno.EROFS, "Read-only file system", "/out/.Lease_0001.pdf.ab12.tmp"),
            "No PDF was made. The folder is read-only.",
        ),
    ],
)
def test_a_pdf_that_cannot_be_saved_comes_back_as_a_result_in_plain_words(
    out: Path, crash: OSError, banner_start: str
) -> None:
    worker, sink, kept = cancelled_run(out, FakeBuild(out, fail=crash))
    worker.process_kept(kept)
    finish(sink, worker)
    assert sink.names.count("error") == 0
    again = sink.events[-1][1]
    assert again.document is None
    assert again.kept_pages == kept.kept_pages  # still on disk, still offered
    assert isinstance(again.error, OSError)
    assert again.error.errno == crash.errno
    assert ".tmp" not in str(again.error)
    assert "Lease_0001" not in str(again.error)
    banner = document_error_banner(again.error, again.raw_dir, again.raw_reason)
    assert banner.text.startswith(banner_start)
    assert ".tmp" not in banner.text
    assert offers_kept(again) is True


def test_an_output_folder_that_is_gone_comes_back_as_the_same_error(out: Path) -> None:
    gone = OutputFolderMissingError("the output folder /out is not an existing folder")
    worker, sink, kept = cancelled_run(out, FakeBuild(out, fail=gone))
    worker.process_kept(kept)
    finish(sink, worker)
    again = sink.events[-1][1]
    assert again.error is gone
    assert again.kept_pages == kept.kept_pages


def test_a_failure_nobody_foresaw_is_still_an_error_for_the_page_to_show(out: Path) -> None:
    crash = RuntimeError("the PDF builder crashed")
    worker, sink, kept = cancelled_run(out, FakeBuild(out, fail=crash))
    worker.process_kept(kept)
    finish(sink, worker)
    assert sink.events[-1] == ("error", crash)
