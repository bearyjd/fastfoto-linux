"""Save, cancel, failure and autosave preserve the review and original pages."""

from dataclasses import replace

import pytest

from fastfoto_linux.documents import DocumentCancelledError
from fastfoto_linux.gui import reviewside
from fastfoto_linux.gui.reviewside import ReviewSide
from fastfoto_linux.gui.state import State, can_cancel, is_busy
from fastfoto_linux.session import DocumentRawReason, DocumentSessionResult
from tests.gui.doc_helpers import clean_document
from tests.gui.review_helpers import draft
from tests.gui.test_controller_documents import Page


def opened(out):
    page = Page(out)
    controller = page.processing()
    side = ReviewSide(controller)
    side.enable()
    result = DocumentSessionResult(
        draft=draft(out), raw_dir=out, raw_reason=DocumentRawReason.REVIEW
    )
    assert side.finished(result)
    return side, page


def test_analysis_enters_review_and_back_checks_scanner(out, monkeypatch):
    monkeypatch.setattr(reviewside, "save_draft", lambda *args: None)
    side, page = opened(out)
    assert page.controller.state.value == "reviewing"
    assert not is_busy(page.controller.state)
    assert not can_cancel(page.controller.state)
    assert side.can_save
    side.back()
    assert page.controller.state is State.CHECKING
    assert "check" in page.worker.names


def test_save_flushes_edits_and_dispatches_the_snapshot(out, monkeypatch):
    saved = []
    monkeypatch.setattr(reviewside, "save_draft", lambda *args: saved.append(args[0]))
    side, page = opened(out)
    calls = []
    page.worker.write_draft = lambda *args: calls.append(args)
    side.edit("toggle", 2)
    side.save()
    assert saved[-1] is calls[0][0]
    assert page.controller.state is State.PROCESSING
    assert side.state.draft.is_included(side.state.draft.pages[1])


@pytest.mark.parametrize("error,cancelled", [(OSError("full"), False), (None, True)])
def test_failed_or_cancelled_save_returns_to_review_with_edits(out, monkeypatch, error, cancelled):
    monkeypatch.setattr(reviewside, "save_draft", lambda *args: None)
    side, page = opened(out)
    page.worker.write_draft = lambda *args: None
    side.edit("rotate", 3, 1)
    snapshot = side.state.draft
    side.save()
    if cancelled:
        page.controller.cancel()
    assert side.finished(DocumentSessionResult(error=error, cancelled=cancelled, draft=snapshot))
    assert page.controller.state.value == "reviewing"
    assert side.state.draft is snapshot
    assert not side.can_delete_originals


def test_an_unexpected_save_error_keeps_the_review(out, monkeypatch):
    monkeypatch.setattr(reviewside, "save_draft", lambda *args: None)
    side, page = opened(out)
    page.worker.write_draft = lambda *args: None
    side.save()
    assert side.error(DocumentCancelledError("cancelled"))
    assert page.controller.state.value == "reviewing"


def test_autosave_failure_is_visible_and_can_be_retried(out, monkeypatch):
    side, page = opened(out)

    def failed(*args):
        raise OSError("full")

    monkeypatch.setattr(reviewside, "save_draft", failed)
    side.edit("toggle", 2)
    assert not side.flush()
    assert side.dirty
    assert "review" in page.controller.banner.text.lower()
    monkeypatch.setattr(reviewside, "save_draft", lambda *args: None)
    assert side.flush()
    assert not side.dirty


def test_success_retains_originals_and_requires_explicit_delete_confirmation(out, monkeypatch):
    monkeypatch.setattr(reviewside, "save_draft", lambda *args: None)
    side, page = opened(out)
    page.worker.write_draft = lambda *args: None
    side.save()
    assert not side.finished(replace(clean_document(out), draft=side.state.draft, raw_dir=out))
    page.controller.on_finished(clean_document(out))
    assert side.can_delete_originals
    with pytest.raises(ValueError):
        side.delete_originals(False)
    assert side.can_delete_originals


def test_old_folder_analysis_uses_the_current_form_duplex(out):
    page = Page(out)
    page.ready()
    side = ReviewSide(page.controller)
    page.controller.set_document_field("both_sides", False)
    calls = []
    page.worker.analyse_folder = lambda *args: calls.append(args)
    side.open_folder(out)
    assert calls[0][1].duplex is False
    assert page.controller.state is State.PROCESSING


def test_folder_open_is_refused_while_another_job_runs(out):
    page = Page(out)
    page.scanning()
    side = ReviewSide(page.controller)
    with pytest.raises(RuntimeError):
        side.open_folder(out)


def test_preview_answer_is_delivered_without_leaving_review(out):
    side, page = opened(out)
    page.worker.preview_page = lambda *args: None
    assert side.preview(3) == ""
    side.preview_ready((3, out / "previews" / "page-0003.jpg", ""))
    assert side.preview_number == 3
    assert side.preview_path.name == "page-0003.jpg"
    assert page.controller.state.value == "reviewing"


def test_failed_flush_vetoes_back_and_replacing_the_open_folder(out, monkeypatch):
    side, page = opened(out)
    side.edit("toggle", 2)

    def fail(*args):
        raise OSError("full")

    monkeypatch.setattr(reviewside, "save_draft", fail)
    side.back()
    assert page.controller.state.value == "reviewing"
    assert not side.open_folder(out)
    assert page.controller.state.value == "reviewing"


def test_draft_settings_are_frozen_when_the_review_opens(out, monkeypatch):
    monkeypatch.setattr(reviewside, "save_draft", lambda *args: None)
    side, page = opened(out)
    page.controller.set_document_field("name", "Later")
    page.controller.set_document_field("both_sides", False)
    calls = []
    page.worker.write_draft = lambda *args: calls.append(args)
    side.save()
    assert calls[0][1].name == "Document"
    assert calls[0][1].duplex
