"""Folder review jobs preserve raw pages and map write failures to review results."""

import threading
from types import SimpleNamespace

import pytest

from fastfoto_linux.documents import DocumentCancelledError, DocumentSettings, OcrMode
from fastfoto_linux.gui.reviewjobs import ReviewJobs
from fastfoto_linux.session import DocumentRawReason
from tests.gui.doc_helpers import DocRecordingSink, clean_document
from tests.gui.review_helpers import draft


def jobs_for(out, *, opener=None, writer=None):
    jobs = []
    sink = DocRecordingSink()
    tools = SimpleNamespace(open_review=opener, write_review=writer, preview_review=None)
    return ReviewJobs(sink, jobs.append, tools), jobs, sink


def test_folder_analysis_requests_thumbnails_and_keeps_originals(out):
    calls = []

    def opener(*args, **kwargs):
        calls.append((args, kwargs))
        return draft(out)

    worker, jobs, sink = jobs_for(out, opener=opener)
    worker.analyse_folder(out, DocumentSettings(output_root=out, ocr=OcrMode.OFF))
    jobs[0](threading.Event())()
    result = sink.value("finished")
    assert result.raw_dir == out
    assert result.raw_reason is DocumentRawReason.REVIEW
    assert result.draft == draft(out)
    assert calls[0][1]["thumbs"] == out / "thumbs"
    assert calls[0][1]["cancel"] is not None


@pytest.mark.parametrize("error", [DocumentCancelledError("cancelled"), OSError("full")])
def test_write_errors_return_the_original_draft_and_pages(out, error):
    def writer(*args, **kwargs):
        raise error

    worker, jobs, sink = jobs_for(out, writer=writer)
    original = draft(out)
    worker.write_draft(original, DocumentSettings(output_root=out, ocr=OcrMode.OFF))
    jobs[0](threading.Event())()
    result = sink.value("finished")
    assert result.draft is original
    assert result.raw_dir == out
    assert len(result.kept_pages) == 3
    assert result.cancelled is isinstance(error, DocumentCancelledError)


def test_successful_write_still_retains_the_original_pages(out):
    worker, jobs, sink = jobs_for(out, writer=lambda *a, **k: clean_document(out).document)
    original = draft(out)
    worker.write_draft(original, DocumentSettings(output_root=out, ocr=OcrMode.OFF))
    jobs[0](threading.Event())()
    result = sink.value("finished")
    assert result.document is not None
    assert result.draft is original
    assert result.raw_reason is DocumentRawReason.REVIEW
    assert result.raw_dir == out
