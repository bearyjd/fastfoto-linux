"""Folder review jobs preserve raw pages and map write failures to review results."""

import stat
import threading
from dataclasses import replace
from types import SimpleNamespace

import pytest
from PIL import Image

from fastfoto_linux.documents import DocumentCancelledError, DocumentSettings, OcrMode
from fastfoto_linux.documents.draft import TrimBox
from fastfoto_linux.gui.reviewjobs import PREVIEW_MAX_PX, ReviewJobs, make_preview
from fastfoto_linux.session import DocumentRawReason
from tests.gui.doc_helpers import DocRecordingSink, clean_document
from tests.gui.review_helpers import draft


def jobs_for(out, *, opener=None, writer=None):
    jobs = []
    sink = DocRecordingSink()
    tools = SimpleNamespace(
        open_review=opener, write_review=writer, preview_review=None, estimate_review=None
    )
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


def test_generated_preview_is_bounded_private_and_leaves_raw_bytes_untouched(out):
    path = out / "page-0001.png"
    Image.new("RGB", (1800, 2400), "white").save(path, dpi=(300, 300))
    original = path.read_bytes()
    page = replace(draft(out).pages[0], trim=TrimBox(0, 0, 0, 0, False))
    source = replace(draft(out), pages=(page,))
    preview = make_preview(source, 1, threading.Event())
    with Image.open(preview) as image:
        assert max(image.size) == PREVIEW_MAX_PX
    assert stat.S_IMODE(preview.stat().st_mode) == 0o600
    assert path.read_bytes() == original


def test_preview_cancel_publishes_nothing(out):
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(DocumentCancelledError):
        make_preview(draft(out), 1, cancel)
    assert not (out / "previews").exists()


def test_preview_refuses_unknown_page_before_reading_anything(out):
    with pytest.raises(ValueError):
        make_preview(draft(out), 99, threading.Event())
