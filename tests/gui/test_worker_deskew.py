"""Seeding reaches only new scans: the session hook, the kept retry, never a past scan."""

from dataclasses import replace

import pytest

from fastfoto_linux.documents import DocumentSettings, OcrMode
from fastfoto_linux.documents.deskew import SkewStatus
from fastfoto_linux.documents.deskew_draft import analyse_and_seed
from fastfoto_linux.gui import reviewjobs
from fastfoto_linux.gui.docform import DocumentForm
from fastfoto_linux.gui.doctools import DocumentTools
from fastfoto_linux.gui.reviewside import ReviewSide
from fastfoto_linux.gui.worker import Worker
from tests.gui.doc_helpers import DocRecordingSink, cancelled_document
from tests.gui.review_helpers import draft
from tests.gui.test_controller_documents import Page
from tests.gui.test_review_cleanup import real_open, synthetic_folder
from tests.gui.test_worker_documents import finish, found


def kept_worker(out, sink, kwargs_seen=None, opener=None):
    def session(request, **kwargs):
        if kwargs_seen is not None:
            kwargs_seen.append(kwargs)
        return cancelled_document(out, 3)

    tools = DocumentTools(
        session=session, open_review=opener or (lambda *args, **kwargs: draft(out))
    )
    return Worker(sink, discover=found, documents=tools)


def test_the_scan_session_gets_the_seeding_analysis(out):
    seen, sink = [], DocRecordingSink()
    worker = kept_worker(out, sink, seen)
    worker.scan_documents(
        DocumentForm(searchable=False, deskew=True), str(out), ocr_available=False, review=True
    )
    finish(sink, worker)
    assert seen[0]["analyse"] is analyse_and_seed


@pytest.mark.parametrize("deskew", [True, False])
def test_the_kept_review_retry_seeds_only_when_the_scan_asked_for_it(out, monkeypatch, deskew):
    calls = []

    def estimate(found_draft, *, cancel=None):
        calls.append(found_draft)
        return found_draft, {1: SkewStatus.LEVEL}

    monkeypatch.setattr(reviewjobs, "estimate_deskew", estimate)
    sink = DocRecordingSink()
    worker = kept_worker(out, sink)
    form = DocumentForm(searchable=False, deskew=deskew)
    worker.scan_documents(form, str(out), ocr_available=False, review=True)
    finish(sink, worker)
    kept = sink.value("finished")
    sink.finished.clear()
    sink.events.clear()
    worker.process_kept(kept)
    finish(sink, worker)
    assert len(calls) == (1 if deskew else 0)
    assert sink.value("finished").draft is not None


def test_opening_a_past_scan_never_estimates_even_with_the_form_box_ticked(out, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("a past scan must not be measured")

    monkeypatch.setattr(reviewjobs, "estimate_deskew", refuse)
    monkeypatch.setattr(reviewjobs, "estimate_page", refuse, raising=False)
    synthetic_folder(out)
    page = Page(out)
    page.ready()
    side = ReviewSide(page.controller)
    page.controller.set_document_field("deskew", True)
    seen = []
    page.worker.analyse_folder = lambda *args: seen.append(args)
    side.open_folder(out)
    assert side._opening_settings.deskew is False
    settings = replace(seen[0][1], ocr=OcrMode.OFF)
    assert isinstance(settings, DocumentSettings) and settings.deskew is False
    assert real_open(out, settings) is not None
