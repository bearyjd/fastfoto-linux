"""Edits to a draft: pure functions on raw numbers, the parts they give."""

import copy
from dataclasses import replace

import pytest

from fastfoto_linux.documents.draft import PageEdit
from fastfoto_linux.documents.draft_edit import (
    move,
    parts,
    rotate,
    set_included,
    set_part_name,
    toggle_split,
)
from fastfoto_linux.documents.errors import DocumentEditError
from tests.documents.edit_helpers import draft_of, layout, numbers


def test_a_draft_without_edits_is_one_part_of_the_kept_pages() -> None:
    draft = draft_of(5, blank={2, 4})
    assert numbers(draft) == [[1, 3, 5]]
    assert not draft.has_edits
    assert (draft.dropped, draft.removed) == ((2, 4), ())


def test_keep_blank_keeps_everything_without_edits() -> None:
    assert numbers(draft_of(3, blank={2}, keep_blank=True)) == [[1, 2, 3]]


# ---- set_included -------------------------------------------------------------------------------


def test_a_page_is_removed_and_the_draft_it_came_from_is_untouched() -> None:
    draft = draft_of(4)
    removed = set_included(draft, 2, False)
    assert numbers(removed) == [[1, 3, 4]]
    assert (removed.removed, removed.dropped) == ((2,), ())
    assert numbers(draft) == [[1, 2, 3, 4]]
    assert not draft.edits


def test_a_page_dropped_as_blank_comes_back() -> None:
    brought = set_included(draft_of(3, blank={2}), 2, True)
    assert numbers(brought) == [[1, 2, 3]]
    assert brought.dropped == ()


def test_setting_what_the_verdict_says_leaves_no_edit() -> None:
    draft = draft_of(3, blank={2})
    assert set_included(draft, 1, True) == draft
    assert set_included(draft, 2, False) == draft
    assert set_included(set_included(draft, 1, False), 1, True) == draft


def test_removing_a_page_with_keep_blank_overrides_it() -> None:
    draft = draft_of(3, blank={2}, keep_blank=True)
    assert numbers(set_included(draft, 2, False)) == [[1, 3]]


@pytest.mark.parametrize("number", [0, 4, -1])
def test_a_page_that_is_not_there_is_refused(number: int) -> None:
    with pytest.raises(DocumentEditError, match=f"page {number}"):
        set_included(draft_of(3), number, False)


def test_the_edit_maps_cannot_be_changed_in_place() -> None:
    removed = set_included(draft_of(3), 2, False)
    with pytest.raises(TypeError):
        removed.edits[1] = PageEdit()  # type: ignore[index]


# ---- rotate -------------------------------------------------------------------------------------


def test_a_page_is_turned_clockwise_and_turns_add_up() -> None:
    draft = rotate(draft_of(3), 2, 1)
    assert layout(draft) == [[(1, 0), (2, 1), (3, 0)]]
    assert layout(rotate(draft, 2, 2)) == [[(1, 0), (2, 3), (3, 0)]]
    assert layout(rotate(draft, 2, 3)) == [[(1, 0), (2, 0), (3, 0)]]
    assert rotate(draft, 2, 3) == draft_of(3)


def test_turns_of_a_blank_page_are_remembered_for_when_it_comes_back() -> None:
    draft = rotate(draft_of(3, blank={2}), 2, 1)
    assert numbers(draft) == [[1, 3]]
    assert layout(set_included(draft, 2, True)) == [[(1, 0), (2, 1), (3, 0)]]


def test_rotating_by_a_whole_turn_or_a_page_not_there_is_refused_or_nothing() -> None:
    assert rotate(draft_of(2), 1, 4) == draft_of(2)
    with pytest.raises(DocumentEditError):
        rotate(draft_of(2), 3, 1)


# ---- move ---------------------------------------------------------------------------------------


def test_a_page_moves_to_a_place_in_the_output_order() -> None:
    draft = draft_of(4)
    assert numbers(move(draft, 4, 0)) == [[4, 1, 2, 3]]
    assert numbers(move(draft, 1, 3)) == [[2, 3, 4, 1]]
    assert numbers(move(move(draft, 4, 0), 4, 2)) == [[1, 2, 4, 3]]
    assert draft.order == ()


@pytest.mark.parametrize("to_index", [-1, 4])
def test_a_place_outside_the_document_is_refused(to_index: int) -> None:
    with pytest.raises(DocumentEditError, match="place"):
        move(draft_of(4), 1, to_index)


def test_moving_a_page_to_where_it_is_changes_nothing() -> None:
    assert move(draft_of(4), 2, 1) == draft_of(4)


# ---- splits and parts ---------------------------------------------------------------------------


def test_a_split_starts_a_new_pdf_at_that_page() -> None:
    assert numbers(toggle_split(draft_of(6), 4)) == [[1, 2, 3], [4, 5, 6]]


def test_toggling_a_split_twice_takes_it_away() -> None:
    draft = draft_of(6)
    assert toggle_split(toggle_split(draft, 4), 4) == draft


def test_two_splits_make_three_parts() -> None:
    assert numbers(toggle_split(toggle_split(draft_of(6), 3), 5)) == [[1, 2], [3, 4], [5, 6]]


def test_a_split_on_the_first_kept_page_does_nothing() -> None:
    assert numbers(toggle_split(draft_of(4), 1)) == [[1, 2, 3, 4]]
    blank_first = toggle_split(draft_of(4, blank={1}), 2)
    assert numbers(blank_first) == [[2, 3, 4]]


def test_a_removed_split_page_passes_the_split_to_the_next_kept_page() -> None:
    draft = set_included(toggle_split(draft_of(6), 3), 3, False)
    assert numbers(draft) == [[1, 2], [4, 5, 6]]


def test_a_split_on_a_page_dropped_as_blank_passes_on_too() -> None:
    assert numbers(toggle_split(draft_of(6, blank={3}), 3)) == [[1, 2], [4, 5, 6]]


def test_a_split_on_the_last_removed_page_does_nothing() -> None:
    draft = set_included(toggle_split(draft_of(4), 4), 4, False)
    assert numbers(draft) == [[1, 2, 3]]


def test_a_part_with_all_its_pages_removed_disappears() -> None:
    draft = toggle_split(toggle_split(draft_of(6), 3), 5)
    for number in (3, 4):
        draft = set_included(draft, number, False)
    assert numbers(draft) == [[1, 2], [5, 6]]


def test_removing_every_page_leaves_no_part() -> None:
    draft = draft_of(3)
    for number in (1, 2, 3):
        draft = set_included(draft, number, False)
    assert numbers(draft) == []


def test_splits_travel_with_their_page_when_the_order_changes() -> None:
    draft = move(toggle_split(draft_of(6), 4), 4, 1)
    assert numbers(draft) == [[1], [4, 2, 3, 5, 6]]
    draft = move(toggle_split(draft_of(6), 5), 1, 5)
    assert numbers(draft) == [[2, 3, 4], [5, 6, 1]]


def test_parts_carry_each_pages_turns() -> None:
    draft = rotate(toggle_split(draft_of(4), 3), 4, 2)
    assert layout(draft) == [[(1, 0), (2, 0)], [(3, 0), (4, 2)]]


# ---- part names ---------------------------------------------------------------------------------


def test_a_part_is_named_in_output_order_and_the_name_is_cleaned() -> None:
    draft = toggle_split(draft_of(4), 3)
    named = set_part_name(set_part_name(draft, 2, " Receipts/2025 "), 1, "Tax return")
    assert dict(named.part_names) == {1: "Tax return", 2: "Receipts 2025"}
    assert [part.name for part in parts(named)] == ["Tax return", "Receipts 2025"]
    assert not draft.part_names


def test_an_empty_name_takes_the_name_away() -> None:
    named = set_part_name(draft_of(2), 1, "Tax")
    assert not set_part_name(named, 1, "  ").part_names


@pytest.mark.parametrize("part", [0, 2])
def test_a_part_that_does_not_exist_cannot_be_named(part: int) -> None:
    with pytest.raises(DocumentEditError, match=f"part {part}"):
        set_part_name(draft_of(3), part, "Tax")


def test_a_name_with_nothing_usable_is_refused() -> None:
    with pytest.raises(DocumentEditError, match="usable"):
        set_part_name(draft_of(3), 1, "..")


def test_edits_are_deep_copy_safe_and_equal_by_value() -> None:
    draft = rotate(set_included(draft_of(3), 2, False), 1, 1)
    assert copy.deepcopy(draft) == draft
    assert replace(draft) == draft
