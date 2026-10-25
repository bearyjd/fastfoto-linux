"""draft_edit.set_crop: pure, the full page is no crop, an otherwise default edit is dropped."""

from dataclasses import replace

import pytest
from fastfoto_linux.documents.page_crop import CROP_UNITS, PageCrop

from fastfoto_linux.documents.draft import PageEdit
from fastfoto_linux.documents.draft_edit import rotate, set_crop, set_included
from fastfoto_linux.documents.errors import DocumentEditError
from tests.documents.edit_helpers import draft_of

CROP = PageCrop(100, 200, 9000, 8000)


def test_a_page_edit_holds_a_crop_or_nothing() -> None:
    assert PageEdit().crop is None
    assert PageEdit(crop=CROP).crop == CROP
    with pytest.raises(ValueError):
        PageEdit(crop=(1, 2, 3, 4))  # type: ignore[arg-type]


def test_set_crop_returns_a_new_draft_and_leaves_the_old_one() -> None:
    draft = draft_of(3)
    cropped = set_crop(draft, 2, CROP)
    assert cropped.edits[2].crop == CROP
    assert draft.edits == {}
    assert cropped is not draft


def test_set_crop_keeps_the_other_parts_of_the_edit() -> None:
    draft = rotate(set_included(draft_of(3), 2, False), 2, 1)
    edit = set_crop(draft, 2, CROP).edits[2]
    assert (edit.include, edit.quarter_turns, edit.crop) == (False, 1, CROP)


def test_the_full_page_is_no_crop() -> None:
    full = PageCrop(0, 0, CROP_UNITS, CROP_UNITS)
    draft = draft_of(2)
    assert set_crop(draft, 1, full) == draft
    assert set_crop(set_crop(draft, 1, CROP), 1, full).edits == {}


def test_clearing_the_only_edit_drops_it() -> None:
    assert set_crop(set_crop(draft_of(2), 1, CROP), 1, None).edits == {}


def test_clearing_a_crop_keeps_the_turn() -> None:
    draft = rotate(set_crop(draft_of(2), 1, CROP), 1, 2)
    assert set_crop(draft, 1, None).edits[1] == replace(PageEdit(), quarter_turns=2)


@pytest.mark.parametrize("bad", [(1, 2, 3, 4), "crop", 5, True])
def test_a_wrong_type_is_refused(bad: object) -> None:
    with pytest.raises(DocumentEditError):
        set_crop(draft_of(2), 1, bad)  # type: ignore[arg-type]


@pytest.mark.parametrize("number", [0, 3, -1])
def test_a_page_that_is_not_there_is_refused(number: int) -> None:
    with pytest.raises(DocumentEditError):
        set_crop(draft_of(2), number, CROP)


def test_a_crop_does_not_change_which_pages_stay() -> None:
    draft = draft_of(3)
    cropped = set_crop(draft, 2, CROP)
    assert cropped.has_edits is draft.has_edits is False
    assert cropped.kept == draft.kept
    assert cropped.order == draft.order and cropped.splits == draft.splits
