"""The worker runs a document scan, and builds a PDF from kept pages, with the run's settings."""

from pathlib import Path
from typing import Any

import pytest

from fastfoto_linux.documents import (
    AllPagesBlankError,
    DocumentCancelledError,
    DocumentSettingsError,
    OcrMode,
    OcrStatus,
)
from fastfoto_linux.gui.docform import DocumentForm
from fastfoto_linux.gui.doctools import DocumentTools
from fastfoto_linux.gui.form import FormInvalidError
from fastfoto_linux.gui.worker import Worker, WorkerBusyError
from fastfoto_linux.scanner import ScanError, ScanTarget
from fastfoto_linux.session import Stage
from tests.cli.fakes import DEVICE
from tests.gui.doc_helpers import (
    PDF_NAME,
    DocRecordingSink,
    FakeBuild,
    ScriptedDocumentSession,
    cancelled_document,
    pages_in,
    stopped_document,
)

WAIT = 10.0


def found() -> ScanTarget:
    return ScanTarget(device=DEVICE)


def worker_for(sink: DocRecordingSink, session: Any, build: Any, **fakes: Any) -> Worker:
    tools = DocumentTools(session=session, build=build)
    return Worker(sink, discover=found, documents=tools, **fakes)


def finish(sink: DocRecordingSink, worker: Worker) -> None:
    assert sink.finished.wait(WAIT)
    worker.join(WAIT)


def scan(worker: Worker, out: Path, form: DocumentForm | None = None, *, ocr: bool = True) -> None:
    worker.scan_documents(form or DocumentForm(), str(out), ocr_available=ocr)


def test_a_scan_builds_the_request_from_the_form(out: Path) -> None:
    sink, session = DocRecordingSink(), ScriptedDocumentSession(out)
    worker = worker_for(sink, session, FakeBuild(out))
    form = DocumentForm(
        name="Lease", colour="grey", dpi=600, both_sides=False, keep_blank=True, langs="eng+deu"
    )
    scan(worker, out, form)
    finish(sink, worker)
    (request,) = session.requests
    assert request.target == found()
    assert (request.dpi, request.duplex) == (600, False)
    assert request.settings.output_root == out
    assert (request.settings.name, request.settings.keep_blank) == ("Lease", True)
    assert request.settings.langs == "eng+deu"
    assert request.settings.ocr is OcrMode.ON


def test_searchable_text_is_off_when_it_cannot_be_made(out: Path) -> None:
    sink, session = DocRecordingSink(), ScriptedDocumentSession(out)
    worker = worker_for(sink, session, FakeBuild(out, ocr=False))
    scan(worker, out, ocr=False)
    finish(sink, worker)
    assert session.requests[0].settings.ocr is OcrMode.OFF


def test_the_stages_pages_and_pdf_progress_reach_the_sink_in_order(out: Path) -> None:
    sink, session = DocRecordingSink(), ScriptedDocumentSession(out, pages=2)
    worker = worker_for(sink, session, FakeBuild(out))
    scan(worker, out)
    finish(sink, worker)
    assert sink.names == [
        "stage",
        "stage",
        "page",
        "page",
        "stage",
        "build_page",
        "build_page",
        "ocr",
        "stage",
        "finished",
    ]
    assert [v for n, v in sink.events if n == "build_page"] == [(1, 2), (2, 2)]
    assert [v for n, v in sink.events if n == "stage"] == [
        Stage.CHECKING,
        Stage.SCANNING,
        Stage.PROCESSING,
        Stage.DONE,
    ]
    assert len(set(sink.threads)) == 1  # every report came from the worker's one thread


def test_the_finished_result_is_the_sessions(out: Path) -> None:
    sink, session = DocRecordingSink(), ScriptedDocumentSession(out, pages=3)
    worker = worker_for(sink, session, FakeBuild(out))
    scan(worker, out)
    finish(sink, worker)
    result = sink.value("finished")
    assert result.document.pdf == out / PDF_NAME
    assert result.document.ocr.status is OcrStatus.DONE


def test_a_bad_form_starts_nothing(out: Path) -> None:
    sink, session = DocRecordingSink(), ScriptedDocumentSession(out)
    worker = worker_for(sink, session, FakeBuild(out))
    with pytest.raises(FormInvalidError) as refused:
        scan(worker, out, DocumentForm(name="///"))
    assert set(refused.value.errors) == {"name"}
    assert session.requests == []
    assert not worker.busy


def test_a_folder_that_is_gone_is_found_unless_the_caller_just_looked(out: Path) -> None:
    sink, session = DocRecordingSink(), ScriptedDocumentSession(out)
    worker = worker_for(sink, session, FakeBuild(out))
    gone = out / "gone"
    with pytest.raises(FormInvalidError) as refused:
        worker.scan_documents(DocumentForm(), str(gone), ocr_available=True)
    assert "output_folder" in refused.value.errors
    worker.scan_documents(DocumentForm(), str(gone), ocr_available=True, checked=True)
    finish(sink, worker)
    assert len(session.requests) == 1  # the session is the authority and refuses it itself


def test_a_refusal_from_the_session_comes_to_the_sink_as_an_error(out: Path) -> None:
    refusal = DocumentSettingsError("the output folder is gone")
    sink = DocRecordingSink()
    worker = worker_for(sink, ScriptedDocumentSession(out, raises=refusal), FakeBuild(out))
    scan(worker, out)
    finish(sink, worker)
    assert sink.names == ["error"]
    assert sink.value("error") is refusal
    assert not worker.busy


def test_a_cancel_reaches_the_session_and_its_result_is_reported(out: Path) -> None:
    sink, session = DocRecordingSink(), ScriptedDocumentSession(out, hold=True)
    worker = worker_for(sink, session, FakeBuild(out))
    scan(worker, out)
    assert session.holding.wait(WAIT)
    worker.cancel()
    finish(sink, worker)
    result = sink.value("finished")
    assert result.cancelled
    assert result.document is None
    assert len(result.kept_pages) == 3


def test_a_document_scan_does_not_run_while_another_job_does(out: Path) -> None:
    sink, session = DocRecordingSink(), ScriptedDocumentSession(out, hold=True)
    worker = worker_for(sink, session, FakeBuild(out))
    scan(worker, out)
    assert session.holding.wait(WAIT)
    with pytest.raises(WorkerBusyError):
        scan(worker, out)
    session.release.set()
    finish(sink, worker)


# -- the pages a part-way scan kept ----------------------------------------------------------


def test_kept_pages_are_made_into_a_pdf_with_the_settings_of_the_run(out: Path) -> None:
    raw = out / ".raw" / "stamp"
    session = ScriptedDocumentSession(out, hold=True)
    build = FakeBuild(out)
    sink = DocRecordingSink()
    worker = worker_for(sink, session, build)
    scan(worker, out, DocumentForm(name="Lease", colour="grey", dpi=200, langs="deu"))
    assert session.holding.wait(WAIT)
    worker.cancel()
    finish(sink, worker)
    kept = sink.value("finished")
    sink.finished.clear()
    sink.events.clear()

    worker.process_kept(kept)
    finish(sink, worker)

    ((pages, settings),) = build.calls
    assert pages == kept.kept_pages == pages_in(raw, 3)
    assert (settings.name, settings.langs, settings.output_root) == ("Lease", "deu", out)
    assert settings.fallback_dpi == 200  # the resolution the pages were scanned at
    assert sink.names == ["stage", "build_page", "build_page", "build_page", "ocr", "finished"]
    assert sink.value("stage") is Stage.PROCESSING
    result = sink.value("finished")
    assert result.document.pdf == out / PDF_NAME
    assert not result.cancelled
    assert result.raw_dir == kept.raw_dir
    assert result.kept_pages == ()


def test_kept_pages_cancelled_again_stay_kept(out: Path) -> None:
    session = ScriptedDocumentSession(out, hold=True)
    build = FakeBuild(out, fail=DocumentCancelledError("stopped before page 2 was processed"))
    sink = DocRecordingSink()
    worker = worker_for(sink, session, build)
    scan(worker, out)
    assert session.holding.wait(WAIT)
    worker.cancel()
    finish(sink, worker)
    kept = sink.value("finished")
    sink.finished.clear()

    worker.process_kept(kept)
    finish(sink, worker)

    again = sink.events[-1][1]
    assert again.cancelled
    assert again.document is None
    assert again.kept_pages == kept.kept_pages
    assert again.error is None


def test_kept_pages_that_cannot_make_a_pdf_come_back_as_an_error_result(out: Path) -> None:
    error = AllPagesBlankError("all 3 pages look blank, so no PDF was written")
    session = ScriptedDocumentSession(out, hold=True)
    sink = DocRecordingSink()
    worker = worker_for(sink, session, FakeBuild(out, fail=error))
    scan(worker, out)
    assert session.holding.wait(WAIT)
    worker.cancel()
    finish(sink, worker)
    kept = sink.value("finished")
    sink.finished.clear()

    worker.process_kept(kept)
    finish(sink, worker)

    again = sink.events[-1][1]
    assert again.error is error
    assert again.kept_pages == kept.kept_pages  # still on disk
    assert sink.names.count("error") == 0


def test_pages_a_scanner_failure_kept_are_made_into_a_pdf_too(out: Path) -> None:
    raw = out / ".raw" / "stamp"
    stopped = stopped_document(raw, ScanError("jam"), pages=2)
    sink = DocRecordingSink()
    build = FakeBuild(out)
    worker = worker_for(sink, ScriptedDocumentSession(out, result=stopped), build)
    scan(worker, out)
    finish(sink, worker)
    sink.finished.clear()
    worker.process_kept(stopped)
    finish(sink, worker)
    assert build.calls[-1][0] == pages_in(raw, 2)


def test_kept_pages_need_a_scan_to_take_the_settings_from(out: Path) -> None:
    worker = worker_for(DocRecordingSink(), ScriptedDocumentSession(out), FakeBuild(out))
    with pytest.raises(RuntimeError, match="no scan has run"):
        worker.process_kept(cancelled_document(out / ".raw" / "stamp"))


def test_a_failure_of_the_build_nobody_foresaw_is_reported_as_an_error(out: Path) -> None:
    crash = RuntimeError("the PDF builder crashed")
    session = ScriptedDocumentSession(out, hold=True)
    sink = DocRecordingSink()
    worker = worker_for(sink, session, FakeBuild(out, fail=crash))
    scan(worker, out)
    assert session.holding.wait(WAIT)
    worker.cancel()
    finish(sink, worker)
    kept = sink.value("finished")
    sink.finished.clear()
    worker.process_kept(kept)
    finish(sink, worker)
    assert sink.events[-1] == ("error", crash)


def test_without_fakes_the_worker_reaches_for_the_real_session_and_nothing_else(out: Path) -> None:
    """The suite refuses the real transport (see conftest): a test that forgot a fake fails."""
    sink = DocRecordingSink()
    worker = Worker(sink, discover=found)
    scan(worker, out)
    finish(sink, worker)
    assert sink.names == ["error"]
