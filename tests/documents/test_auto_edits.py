"""Per-page output choices stay attached to raw page numbers and preserve other edits."""

from dataclasses import replace

import pytest

from fastfoto_linux.documents.auto_colour import ColourDecision, ColourReason, page_colour
from fastfoto_linux.documents.draft import PageEdit
from fastfoto_linux.documents.draft_edit import (
    PageEdits,
    move,
    rotate,
    set_colour,
    set_included,
    toggle_split,
    validate_edits,
    with_edits,
)
from fastfoto_linux.documents.errors import DocumentEditError
from fastfoto_linux.documents.modes import ColourMode, ColourPolicy
from tests.documents.edit_helpers import draft_of


def test_override_and_clear_are_pure_and_keep_include_rotation_and_splits() -> None:
    draft = rotate(set_included(toggle_split(draft_of(3), 2), 2, False), 2, 1)
    changed = set_colour(draft, 2, ColourPolicy.GREY)
    assert changed.edits[2] == PageEdit(False, 1, ColourPolicy.GREY)
    assert draft.edits[2] == PageEdit(False, 1)
    assert changed.splits == draft.splits
    assert set_colour(changed, 2, None) == draft


def test_an_explicit_choice_is_retained_even_when_it_matches_document_policy() -> None:
    changed = set_colour(draft_of(2), 1, ColourPolicy.COLOUR)
    assert changed.edits[1].colour is ColourPolicy.COLOUR
    assert changed.has_edits
    assert set_colour(changed, 1, None).edits == {}


def test_auto_and_manual_overrides_stay_with_raw_numbers_after_move() -> None:
    draft = draft_of(2)
    decision = ColourDecision(ColourMode.COLOUR, ColourMode.BW, ColourReason.BILEVEL)
    draft = replace(draft, pages=tuple(replace(page, colour=decision) for page in draft.pages))
    draft = set_colour(set_colour(draft, 1, ColourPolicy.AUTO), 2, ColourPolicy.COLOUR)
    draft = move(draft, 2, 0)
    assert page_colour(draft, draft.pages[0], ColourPolicy.GREY) is ColourMode.BW
    assert page_colour(draft, draft.pages[1], ColourPolicy.GREY) is ColourMode.COLOUR
    assert draft.order == (2, 1)


def test_bulk_overrides_can_set_and_clear_without_losing_existing_edits() -> None:
    draft = set_colour(draft_of(3), 1, ColourPolicy.GREY)
    changed = with_edits(draft, PageEdits(colour={1: None, 3: ColourPolicy.AUTO}, rotate={3: 2}))
    assert 1 not in changed.edits
    assert changed.edits[3] == PageEdit(None, 2, ColourPolicy.AUTO)


@pytest.mark.parametrize("number", [0, 4])
def test_bulk_colour_numbers_are_checked_before_reading_pages(number: int) -> None:
    with pytest.raises(DocumentEditError, match="page"):
        validate_edits(PageEdits(colour={number: ColourPolicy.AUTO}), 3)


def test_direct_colour_edit_checks_page_number() -> None:
    with pytest.raises(DocumentEditError, match="page"):
        set_colour(draft_of(2), 3, ColourPolicy.AUTO)
