"""Explicit deletion and navigation cannot discard changed or unflushed originals."""

import os
from dataclasses import replace

import pytest

from fastfoto_linux.documents import OcrStatus
from fastfoto_linux.gui import reviewside
from fastfoto_linux.gui.state import Mode, State
from fastfoto_linux.session import DocumentSessionResult
from tests.gui.doc_helpers import clean_document
from tests.gui.test_reviewside import opened


def saved(out, monkeypatch):
    monkeypatch.setattr(reviewside, "save_draft", lambda *args: None)
    side, page = opened(out)
    page.worker.write_draft = lambda *args: None
    side.save()
    result = replace(clean_document(out), draft=side.state.draft, raw_dir=out)
    page.controller.on_finished(result)
    assert side.can_delete_originals
    return side, page


def test_deletion_before_save_is_refused(out):
    side, _page = opened(out)
    with pytest.raises(RuntimeError):
        side.delete_originals(True)
    assert len(list(out.glob("page-*.png"))) == 3


def test_confirmed_deletion_removes_only_tracked_originals(out, monkeypatch):
    side, _page = saved(out, monkeypatch)
    unknown = out / "unrelated.txt"
    unknown.write_text("synthetic")
    side.delete_originals(True)
    assert not list(out.glob("page-*.png"))
    assert unknown.read_text() == "synthetic"
    assert not side.can_delete_originals
    assert not side.can_reopen


@pytest.mark.parametrize("change", ["content", "replacement", "symlink"])
def test_modified_or_replaced_pages_veto_all_deletion(out, monkeypatch, change):
    side, _page = saved(out, monkeypatch)
    path = out / "page-0002.png"
    if change == "content":
        path.write_bytes(b"changed")
    elif change == "replacement":
        path.rename(out / "older.png")
        path.write_bytes(b"synthetic!")
        os.utime(path, ns=(1, 1))
    else:
        path.unlink()
        path.symlink_to(out / "page-0001.png")
    with pytest.raises((OSError, ValueError)):
        side.delete_originals(True)
    assert (out / "page-0001.png").exists()
    assert (out / "page-0003.png").exists()


def test_folder_symlink_redirection_vetoes_deletion(out, monkeypatch):
    side, _page = saved(out, monkeypatch)
    original = out.with_name("old-originals")
    out.rename(original)
    redirected = out.with_name("redirected")
    redirected.mkdir()
    target = redirected / "page-0001.png"
    target.write_text("unrelated")
    out.symlink_to(redirected, target_is_directory=True)
    with pytest.raises((OSError, ValueError)):
        side.delete_originals(True)
    assert len(list(original.glob("page-*.png"))) == 3
    assert target.read_text() == "unrelated"


@pytest.mark.parametrize("action", ["check", "mode", "close", "scan"])
def test_failed_flush_blocks_all_controller_entry_points(out, monkeypatch, action):
    side, page = opened(out)
    side.edit("rotate", 3, 1)

    def fail(*args):
        raise OSError("full")

    monkeypatch.setattr(reviewside, "save_draft", fail)
    if action == "check":
        page.controller.check_scanner()
    elif action == "mode":
        page.controller.set_mode(Mode.PHOTOS)
    elif action == "close":
        assert not page.controller.request_close()
    else:
        with pytest.raises(RuntimeError):
            page.controller.start_scan()
    assert page.controller.state is State.REVIEWING
    assert page.controller.mode is Mode.DOCUMENTS
    assert side.dirty


def test_stale_preview_answers_do_not_replace_current_or_closed_review(out, monkeypatch):
    monkeypatch.setattr(reviewside, "save_draft", lambda *args: None)
    side, page = opened(out)
    page.worker.preview_page = lambda *args: None
    side.preview(3)
    side.preview_ready((side.state.draft, 1, out / "previews" / "page-0001.jpg", ""))
    assert side.preview_path is None
    side.back()
    side.preview_ready((side.state.draft, 3, out / "previews" / "page-0003.jpg", ""))
    assert side.preview_path is None


@pytest.mark.parametrize("ocr", [OcrStatus.FAILED, OcrStatus.TIMED_OUT])
def test_failed_ocr_returns_to_review_without_deletion_offer(out, monkeypatch, ocr):
    monkeypatch.setattr(reviewside, "save_draft", lambda *args: None)
    side, page = opened(out)
    page.worker.write_draft = lambda *args: None
    side.save()
    result = replace(clean_document(out, ocr=ocr), draft=side.state.draft, raw_dir=out)
    page.controller.on_finished(result)
    assert page.controller.state is State.REVIEWING
    assert not side.can_delete_originals
    assert page.controller.banner is not None


def test_failed_open_restores_the_old_drafts_frozen_save_settings(out, monkeypatch):
    monkeypatch.setattr(reviewside, "save_draft", lambda *args: None)
    side, page = opened(out)
    page.controller.set_document_field("name", "Later")
    page.worker.analyse_folder = lambda *args: None
    side.open_folder(out / "missing")
    page.controller.on_finished(DocumentSessionResult(error=OSError("missing")))
    calls = []
    page.worker.write_draft = lambda *args: calls.append(args)
    side.save()
    assert calls[0][1].name == "Document"


def test_preview_source_and_path_must_match_current_request(out):
    side, page = opened(out)
    page.worker.preview_page = lambda *args: None
    side.preview(3)
    source = side.state.draft
    other = replace(source, raw_dir=out / "other")
    side.preview_ready((other, 3, out / "other" / "previews" / "page-0003.jpg", ""))
    assert side.preview_path is None
    side.preview_ready((source, 3, out / "other" / "previews" / "page-0003.jpg", ""))
    assert side.preview_path is None
    side.preview_ready((source, 3, out / "previews" / "page-0003.jpg", ""))
    assert side.preview_path == out / "previews" / "page-0003.jpg"


def test_deletion_cleans_known_artifacts_and_preserves_newer_or_unknown_files(out, monkeypatch):
    monkeypatch.setattr(reviewside, "save_draft", lambda *args: None)
    side, page = opened(out)
    thumb = out / "thumbs" / "page-0001.jpg"
    preview = out / "previews" / "page-0001.jpg"
    for path in (thumb, preview):
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"synthetic")
    unknown = thumb.with_name("unrelated.jpg")
    unknown.write_bytes(b"unrelated")
    sidecar = out / "review.json"
    sidecar.write_bytes(b"old")
    page.worker.write_draft = lambda *args: None
    side.save()
    page.controller.on_finished(replace(clean_document(out), draft=side.state.draft, raw_dir=out))
    sidecar.write_bytes(b"newer review")
    side.delete_originals(True)
    assert not thumb.exists()
    assert not preview.exists()
    assert unknown.read_bytes() == b"unrelated"
    assert sidecar.read_bytes() == b"newer review"
