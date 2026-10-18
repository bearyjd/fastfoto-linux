"""The sidecar: ``review.json`` beside the raw pages and the thumbnails next to it. A draft is
saved atomically and privately, comes back as it was, and is reused only while the pages and the
analysis are the ones it was made from."""

import os
import stat
from dataclasses import replace
from pathlib import Path

import pytest

from fastfoto_linux.documents import ColourMode, OcrMode
from fastfoto_linux.documents import draft_store as store
from fastfoto_linux.documents.draft_edit import set_part_name, toggle_split
from fastfoto_linux.documents.draft_store import (
    REVIEW_FILE,
    THUMBS_DIR,
    StoredOptions,
    load_draft,
    open_draft,
    read_review,
    save_draft,
)
from fastfoto_linux.session.raw import list_pages
from tests.documents.store_helpers import (
    analysed,
    edited,
    raw_folder,
    store_settings,
    touch_page,
)


@pytest.fixture
def folder_and_pages(tmp_path: Path) -> tuple[Path, tuple[Path, ...]]:
    return raw_folder(tmp_path)


@pytest.fixture
def out(tmp_path: Path) -> Path:
    path = tmp_path / "out"
    path.mkdir()
    return path


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_a_draft_comes_back_as_it_was_saved(folder_and_pages, out) -> None:
    folder, pages = folder_and_pages
    settings = store_settings(out)
    draft = edited(analysed(folder, pages, settings))
    save_draft(draft, settings)
    loaded = load_draft(folder, pages, settings)
    assert loaded is not None
    assert loaded.pages == draft.pages
    assert dict(loaded.edits) == dict(draft.edits)
    assert (loaded.order, loaded.splits) == (draft.order, draft.splits)
    assert (loaded.duplex, loaded.keep_blank, loaded.raw_dir) == (True, False, folder)
    assert [p.thumb for p in loaded.pages] == [f"page-{n:04d}.jpg" for n in range(1, 5)]
    assert loaded.edits and loaded.order and loaded.splits  # the edits were not empty


def test_the_cached_analysis_keeps_flags_marks_and_partners(folder_and_pages, out) -> None:
    folder, pages = folder_and_pages
    settings = store_settings(out)
    draft = analysed(folder, pages, settings)
    save_draft(draft, settings)
    loaded = load_draft(folder, pages, settings)
    assert loaded is not None
    assert any(p.marks for p in draft.pages)
    assert [(p.partner, p.flags, p.marks, p.detail) for p in loaded.pages] == [
        (p.partner, p.flags, p.marks, p.detail) for p in draft.pages
    ]
    assert all(p.ink is None and p.encoded is None for p in loaded.pages)


def test_the_options_of_the_document_come_back(folder_and_pages, out) -> None:
    folder, pages = folder_and_pages
    settings = store_settings(out, name="Tax return", colour=ColourMode.GREY, langs="eng+deu")
    save_draft(analysed(folder, pages, settings), settings)
    stored = read_review(folder, pages)
    assert stored is not None
    assert stored.options == StoredOptions("Tax return", ColourMode.GREY, OcrMode.OFF, "eng+deu")


def test_part_names_are_saved_and_restored(folder_and_pages, out) -> None:
    folder, pages = folder_and_pages
    settings = store_settings(out)
    draft = toggle_split(analysed(folder, pages, settings), 3)
    draft = set_part_name(set_part_name(draft, 1, "Tax return"), 2, "Receipts")
    save_draft(draft, settings)
    loaded = load_draft(folder, pages, settings)
    assert loaded is not None
    assert dict(loaded.part_names) == {1: "Tax return", 2: "Receipts"}


def test_no_sidecar_is_no_draft_and_no_complaint(folder_and_pages, out, caplog) -> None:
    folder, pages = folder_and_pages
    assert load_draft(folder, pages, store_settings(out)) is None
    assert read_review(folder, pages) is None
    assert not [r for r in caplog.records if r.levelname in ("WARNING", "ERROR")]


def test_the_pages_listing_ignores_the_sidecar_and_the_thumbnails(folder_and_pages, out) -> None:
    folder, pages = folder_and_pages
    settings = store_settings(out)
    save_draft(analysed(folder, pages, settings), settings)
    assert (folder / REVIEW_FILE).is_file()
    assert (folder / THUMBS_DIR / "page-0001.jpg").is_file()
    assert list_pages(folder) == pages


@pytest.mark.parametrize("umask", [0o000, 0o022, 0o077])
def test_files_are_private_whatever_the_umask(tmp_path, out, umask) -> None:
    previous = os.umask(umask)
    try:
        folder, pages = raw_folder(tmp_path)
        settings = store_settings(out)
        save_draft(analysed(folder, pages, settings), settings)
    finally:
        os.umask(previous)
    assert mode(folder / REVIEW_FILE) == 0o600
    assert mode(folder / THUMBS_DIR) == 0o700
    assert {mode(p) for p in (folder / THUMBS_DIR).iterdir()} == {0o600}


def test_saving_again_keeps_the_mode_and_leaves_no_temporary_file(folder_and_pages, out) -> None:
    folder, pages = folder_and_pages
    settings = store_settings(out)
    draft = analysed(folder, pages, settings)
    save_draft(draft, settings)
    before = sorted(p.name for p in folder.iterdir())
    save_draft(edited(draft), settings)
    assert sorted(p.name for p in folder.iterdir()) == before
    assert mode(folder / REVIEW_FILE) == 0o600


def test_a_crash_before_the_replace_leaves_the_old_file(
    folder_and_pages, out, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder, pages = folder_and_pages
    settings = store_settings(out)
    draft = analysed(folder, pages, settings)
    save_draft(draft, settings)
    old = (folder / REVIEW_FILE).read_bytes()
    listing = sorted(p.name for p in folder.iterdir())

    def crash(*_args: object, **_kwargs: object) -> None:
        raise OSError("power cut")

    monkeypatch.setattr(store.os, "replace", crash)
    with pytest.raises(OSError, match="power cut"):
        save_draft(edited(draft), settings)
    assert (folder / REVIEW_FILE).read_bytes() == old
    assert sorted(p.name for p in folder.iterdir()) == listing


def test_a_draft_without_a_folder_cannot_be_saved(folder_and_pages, out) -> None:
    folder, pages = folder_and_pages
    draft = replace(analysed(folder, pages, store_settings(out)), raw_dir=None)
    with pytest.raises(ValueError, match="folder"):
        save_draft(draft)


def test_a_fresh_cache_is_used_without_analysing_again(
    folder_and_pages, out, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder, pages = folder_and_pages
    settings = store_settings(out)
    draft = edited(analysed(folder, pages, settings))
    save_draft(draft, settings)

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("the pages were analysed again")

    monkeypatch.setattr(store, "analyse_document", refuse)
    opened = open_draft(folder, pages, settings)
    assert opened.pages == draft.pages
    assert dict(opened.edits) == dict(draft.edits)


def test_fresh_ignores_the_sidecar(folder_and_pages, out) -> None:
    folder, pages = folder_and_pages
    settings = store_settings(out)
    fresh = analysed(folder, pages, settings)
    save_draft(edited(fresh), settings)
    opened = open_draft(folder, pages, settings, fresh=True)
    assert opened.pages == fresh.pages
    assert not opened.has_edits


def _stale_page(folder: Path, pages: tuple[Path, ...]) -> None:
    touch_page(pages[0])


def _grown_page(folder: Path, pages: tuple[Path, ...]) -> None:
    with pages[1].open("ab") as page:
        page.write(b"\x00")


def _old_analysis(folder: Path, pages: tuple[Path, ...]) -> None:
    store.ANALYSIS_VERSION += 1


@pytest.mark.parametrize("change", [_stale_page, _grown_page, _old_analysis])
def test_a_stale_cache_is_analysed_again_and_the_edits_kept(
    folder_and_pages, out, monkeypatch: pytest.MonkeyPatch, change
) -> None:
    folder, pages = folder_and_pages
    settings = store_settings(out)
    draft = edited(analysed(folder, pages, settings))
    save_draft(draft, settings)
    monkeypatch.setattr(store, "ANALYSIS_VERSION", store.ANALYSIS_VERSION)
    change(folder, pages)
    assert load_draft(folder, pages, settings) is None
    calls: list[int] = []
    real = store.analyse_document
    monkeypatch.setattr(store, "analyse_document", lambda *a, **k: calls.append(1) or real(*a, **k))
    opened = open_draft(folder, pages, settings)
    assert calls == [1]
    assert dict(opened.edits) == dict(draft.edits)
    assert (opened.order, opened.splits) == (draft.order, draft.splits)


@pytest.mark.parametrize("changes", [{"duplex": False}, {"keep_blank": True}])
def test_another_pairing_or_blank_rule_is_not_served_from_the_cache(
    folder_and_pages, out, changes
) -> None:
    folder, pages = folder_and_pages
    settings = store_settings(out)
    save_draft(analysed(folder, pages, settings), settings)
    other = replace(settings, **changes)
    assert load_draft(folder, pages, other) is None
    opened = open_draft(folder, pages, other)
    assert (opened.duplex, opened.keep_blank) == (other.duplex, other.keep_blank)


def test_a_different_set_of_pages_takes_no_edits(folder_and_pages, out) -> None:
    folder, pages = folder_and_pages
    settings = store_settings(out)
    save_draft(edited(analysed(folder, pages, settings)), settings)
    pages[3].rename(folder / "page-0009.png")
    opened = open_draft(folder, list_pages(folder), settings)
    assert not opened.has_edits
    assert len(opened.pages) == 4
