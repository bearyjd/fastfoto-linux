"""Review edits retain raw identities and flags only explain the verdict."""

from dataclasses import FrozenInstanceError

import pytest

from fastfoto_linux.gui.review import ReviewState, review_items, review_summary
from tests.gui.review_helpers import draft


def test_review_items_keep_blank_pages_visible_and_flags_are_hints(tmp_path):
    state = ReviewState(draft(tmp_path))
    items = review_items(state)
    assert [item.number for item in items] == [1, 2, 3]
    assert [item.included for item in items] == [True, False, True]
    assert items[1].dropped
    assert items[2].flags == ("few_marks",)
    assert "marks" in items[2].flag_text.lower()
    with pytest.raises(FrozenInstanceError):
        state.focus = 2


def test_edits_return_new_states_with_split_parts_and_names(tmp_path):
    original = ReviewState(draft(tmp_path))
    state = original.toggle(2).rotate(3, -1).move(3, 0).toggle_split(2).name_part(2, "Second")
    assert [item.number for item in review_items(original)] == [1, 2, 3]
    assert [item.number for item in review_items(state)] == [3, 1, 2]
    assert review_items(state)[0].turns == 3
    assert review_items(state)[2].starts_part
    assert state.draft.part_names[2] == "Second"
    assert "3 pages" in review_summary(state)
    assert "2 PDFs" in review_summary(state)


def test_filter_and_focus_do_not_change_edits(tmp_path):
    state = ReviewState(draft(tmp_path)).only_flagged(True).focused(3)
    assert [item.number for item in review_items(state)] == [3]
    assert state.focus == 3
    assert not state.draft.has_edits


@pytest.mark.parametrize("operation", ["toggle", "rotate", "move", "toggle_split", "focused"])
def test_unknown_raw_numbers_are_refused(tmp_path, operation):
    state = ReviewState(draft(tmp_path))
    with pytest.raises(ValueError):
        if operation in {"rotate", "move"}:
            getattr(state, operation)(99, 1)
        else:
            getattr(state, operation)(99)
