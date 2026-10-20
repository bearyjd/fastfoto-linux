"""Auto and per-page overrides must reach actual PDF representations and leave sources intact."""

from dataclasses import replace
from pathlib import Path

import pytest

from fastfoto_linux.documents.analyse import analyse_document
from fastfoto_linux.documents.draft import PageEdit
from fastfoto_linux.documents.draft_edit import move, rotate, set_colour, set_included, toggle_split
from fastfoto_linux.documents.modes import ColourMode, ColourPolicy
from fastfoto_linux.documents.settings import DocumentSettings
from fastfoto_linux.documents.write import write_document
from tests.documents.auto_helpers import pdf_modes, source_hashes, write_auto_pages
from tests.documents.draft_helpers import hand_draft
from tests.documents.store_helpers import store_settings


@pytest.fixture
def out(tmp_path: Path) -> Path:
    folder = tmp_path / "out"
    folder.mkdir()
    return folder


def test_mixed_auto_pdf_uses_colour_grey_and_bilevel_pages(tmp_path: Path, out: Path) -> None:
    pages = write_auto_pages(tmp_path / "pages", ("stamp", "gradient", "text"))
    original = source_hashes(pages)
    settings = store_settings(out, keep_blank=True, duplex=False)
    draft = analyse_document(pages, settings)
    assert all(page.colour is not None for page in draft.pages)
    result = write_document(draft, replace(settings, colour=ColourPolicy.AUTO))
    assert pdf_modes(result.pdf) == ["/DeviceRGB", "/DeviceGray", "bw"]
    assert source_hashes(pages) == original


@pytest.mark.parametrize("keep_blank", [False, True])
def test_decisions_exist_for_blank_pages_even_when_judging_is_skipped(
    tmp_path: Path, out: Path, keep_blank: bool
) -> None:
    pages = write_auto_pages(tmp_path / "pages", ("text", "blank"))
    draft = analyse_document(
        pages, store_settings(out, keep_blank=keep_blank, duplex=False), encode=False
    )
    assert all(page.colour is not None for page in draft.pages)
    assert draft.pages[1].blank is (not keep_blank)
    assert draft.kept == (draft.pages if keep_blank else draft.pages[:1])


def test_cached_bilevel_bytes_do_not_survive_a_colour_override(tmp_path: Path, out: Path) -> None:
    pages = write_auto_pages(tmp_path / "pages", ("stamp",))
    original = source_hashes(pages)
    settings = store_settings(out, colour=ColourMode.BW, duplex=False)
    draft = hand_draft(pages, settings)
    assert draft.pages[0].encoded is not None
    assert draft.pages[0].encoded.mode is ColourMode.BW
    changed = set_colour(draft, 1, ColourPolicy.COLOUR)
    assert pdf_modes(write_document(changed, settings).pdf) == ["/DeviceRGB"]
    reset = set_colour(changed, 1, None)
    assert pdf_modes(write_document(reset, settings).pdf) == ["bw"]
    assert source_hashes(pages) == original


def test_changed_manual_policy_invalidates_the_existing_encoded_mode(
    tmp_path: Path, out: Path
) -> None:
    pages = write_auto_pages(tmp_path / "pages", ("stamp",))
    settings = store_settings(out, colour=ColourMode.BW, duplex=False)
    draft = hand_draft(pages, settings)
    result = write_document(draft, replace(settings, colour=ColourMode.COLOUR))
    assert pdf_modes(result.pdf) == ["/DeviceRGB"]


def test_override_survives_turn_move_split_and_restoring_a_dropped_page(
    tmp_path: Path, out: Path
) -> None:
    pages = write_auto_pages(tmp_path / "pages", ("stamp", "gradient", "text"))
    original = source_hashes(pages)
    settings = store_settings(out, duplex=False)
    draft = hand_draft(pages, settings, blank={3})
    draft = set_colour(draft, 1, ColourPolicy.BW)
    draft = set_colour(draft, 2, ColourPolicy.GREY)
    draft = set_colour(draft, 3, ColourPolicy.COLOUR)
    draft = move(toggle_split(rotate(set_included(draft, 3, True), 2, 1), 1), 2, 0)
    result = write_document(draft, settings)
    assert [pdf_modes(part.pdf) for part in result.parts] == [["/DeviceGray"], ["bw", "/DeviceRGB"]]
    assert result.pages_in_pdf == 3
    assert draft.edits[2] == PageEdit(None, 1, ColourPolicy.GREY)
    assert source_hashes(pages) == original


def test_auto_without_a_persisted_decision_reclassifies_retained_raw(
    tmp_path: Path, out: Path
) -> None:
    pages = write_auto_pages(tmp_path / "pages", ("stamp",))
    settings = store_settings(out, duplex=False)
    draft = set_colour(hand_draft(pages, settings), 1, ColourPolicy.AUTO)
    assert draft.pages[0].colour is None
    assert pdf_modes(write_document(draft, settings).pdf) == ["/DeviceRGB"]


def test_default_document_request_remains_colour(out: Path) -> None:
    assert DocumentSettings(out).colour is ColourMode.COLOUR
