"""``with_edits``: the command line's edits in one call, and what it refuses."""

import pytest

from fastfoto_linux.documents.draft_edit import PageEdits, validate_edits, with_edits
from fastfoto_linux.documents.errors import DocumentEditError
from tests.documents.edit_helpers import draft_of, layout, numbers


def test_no_edits_give_the_same_draft() -> None:
    draft = draft_of(4, blank={2})
    assert with_edits(draft, PageEdits()) == draft


def test_every_kind_of_edit_at_once() -> None:
    edits = PageEdits(
        drop=frozenset({1}),
        keep=frozenset({2}),
        rotate={3: 1, 4: 3},
        split=frozenset({4}),
        order=(4, 3, 2, 1, 5),
    )
    draft = with_edits(draft_of(5, blank={2}), edits)
    # order 4, 3, 2, 1, 5: page 1 is removed, the split on 4 is on the first kept page
    assert layout(draft) == [[(4, 3), (3, 1), (2, 0), (5, 0)]]
    assert draft.removed == (1,)


def test_edits_start_from_the_edits_the_draft_already_has() -> None:
    first = with_edits(draft_of(4), PageEdits(drop=frozenset({1})))
    second = with_edits(first, PageEdits(rotate={2: 2}))
    assert layout(second) == [[(2, 2), (3, 0), (4, 0)]]


def test_the_order_is_taken_before_the_splits() -> None:
    edits = PageEdits(order=(3, 4, 1, 2), split=frozenset({1}))
    assert numbers(with_edits(draft_of(4), edits)) == [[3, 4], [1, 2]]


def test_keep_blank_with_drop_still_drops() -> None:
    draft = draft_of(3, keep_blank=True)
    assert numbers(with_edits(draft, PageEdits(drop=frozenset({2})))) == [[1, 3]]


def test_a_page_brought_back_that_was_never_dropped_changes_nothing() -> None:
    draft = draft_of(3)
    assert with_edits(draft, PageEdits(keep=frozenset({2}))) == draft


@pytest.mark.parametrize(
    ("edits", "message"),
    [
        (PageEdits(drop=frozenset({5})), "page 5"),
        (PageEdits(keep=frozenset({0})), "page 0"),
        (PageEdits(rotate={9: 1}), "page 9"),
        (PageEdits(split=frozenset({7})), "page 7"),
        (PageEdits(drop=frozenset({2}), keep=frozenset({2})), "both"),
        (PageEdits(rotate={1: 0}), "angle"),
        (PageEdits(rotate={1: 4}), "angle"),
        (PageEdits(order=(1, 2, 3)), "permutation"),
        (PageEdits(order=(1, 2, 2, 3)), "permutation"),
        (PageEdits(order=(1, 2, 3, 5)), "permutation"),
    ],
)
def test_edits_that_cannot_be_made_are_refused_by_validate_edits(
    edits: PageEdits, message: str
) -> None:
    with pytest.raises(DocumentEditError, match=message):
        validate_edits(edits, 4)
    with pytest.raises(DocumentEditError, match=message):
        with_edits(draft_of(4), edits)


def test_a_part_name_for_a_part_that_does_not_exist_is_refused() -> None:
    with pytest.raises(DocumentEditError, match="part 2"):
        with_edits(draft_of(4), PageEdits(part_names={2: "Receipts"}))
    ok = with_edits(draft_of(4), PageEdits(split=frozenset({3}), part_names={2: "Receipts"}))
    assert dict(ok.part_names) == {2: "Receipts"}


def test_valid_edits_pass_validation() -> None:
    validate_edits(PageEdits(order=(2, 1, 4, 3), rotate={1: 1}), 4)
