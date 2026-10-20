"""Edits to a draft as pure functions: each returns a new draft and never changes its input.

Pages are named by raw number (their place, counting from 1, in the list the draft was made
from). ``order`` is the output order, empty for the raw order. A split is anchored on a page
("page n starts a new PDF"); if that page is left out, the next page that stays starts the PDF,
a PDF with no page left disappears, and a split on the first page that stays does nothing.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType

from fastfoto_linux.documents.draft import (
    QUARTER_TURNS,
    DocumentDraft,
    OutputPart,
    PageAnalysis,
    PageEdit,
)
from fastfoto_linux.documents.errors import DocumentEditError
from fastfoto_linux.documents.modes import ColourPolicy
from fastfoto_linux.output.errors import InvalidPrefixError
from fastfoto_linux.output.naming import sanitise_prefix


@dataclass(frozen=True)
class PageEdits:
    """Edits as the command line gives them, in raw numbers: pages to leave out, to bring back,
    pages turned (clockwise quarter turns, 1 to 3), pages that start a new PDF, a full order
    (empty: raw order) and the names of the parts (counted from 1, in output order)."""

    drop: frozenset[int] = frozenset()
    keep: frozenset[int] = frozenset()
    rotate: Mapping[int, int] = field(default_factory=dict)
    split: frozenset[int] = frozenset()
    order: tuple[int, ...] = ()
    part_names: Mapping[int, str] = field(default_factory=dict)
    colour: Mapping[int, ColourPolicy | None] = field(default_factory=dict)


def _page(draft: DocumentDraft, number: int) -> PageAnalysis:
    if not 1 <= number <= len(draft.pages):
        raise DocumentEditError(
            f"page {number} is not in the document, which has {len(draft.pages)} pages"
        )
    return draft.pages[number - 1]


def _with_page_edit(draft: DocumentDraft, number: int, edit: PageEdit) -> DocumentDraft:
    edits = dict(draft.edits)
    if edit == PageEdit():
        edits.pop(number, None)
    else:
        edits[number] = edit
    return replace(draft, edits=MappingProxyType(edits))


def _order(draft: DocumentDraft) -> tuple[int, ...]:
    return draft.order or tuple(range(1, len(draft.pages) + 1))


def _with_order(draft: DocumentDraft, order: Iterable[int]) -> DocumentDraft:
    """``draft`` in this order; the raw order is stored as no order, so equal drafts are equal."""
    order = tuple(order)
    return replace(draft, order=() if order == tuple(range(1, len(order) + 1)) else order)


def set_included(draft: DocumentDraft, number: int, keep: bool) -> DocumentDraft:
    """``number`` stays (``keep``) or is left out. What the verdict already says is no edit."""
    page = _page(draft, number)
    edit = draft.edits.get(number, PageEdit())
    follows_verdict = keep == (draft.keep_blank or not page.blank)
    return _with_page_edit(draft, number, replace(edit, include=None if follows_verdict else keep))


def rotate(draft: DocumentDraft, number: int, turns: int) -> DocumentDraft:
    """``number`` turned ``turns`` more quarter turns clockwise."""
    _page(draft, number)
    edit = draft.edits.get(number, PageEdit())
    return _with_page_edit(
        draft, number, replace(edit, quarter_turns=(edit.quarter_turns + turns) % QUARTER_TURNS)
    )


def move(draft: DocumentDraft, number: int, to_index: int) -> DocumentDraft:
    """``number`` at place ``to_index`` (counting from 0) of the output order."""
    _page(draft, number)
    if not 0 <= to_index < len(draft.pages):
        raise DocumentEditError(
            f"place {to_index} is not in a document of {len(draft.pages)} pages (0 is the first)"
        )
    order = [n for n in _order(draft) if n != number]
    order.insert(to_index, number)
    return _with_order(draft, order)


def toggle_split(draft: DocumentDraft, number: int) -> DocumentDraft:
    """A new PDF starts at ``number``, or no longer does."""
    _page(draft, number)
    return replace(draft, splits=draft.splits.symmetric_difference({number}))


def set_part_name(draft: DocumentDraft, part: int, name: str) -> DocumentDraft:
    """PDF number ``part`` (from 1, in output order) is named ``name``, cleaned like an album
    name. An empty name takes the name away."""
    count = len(parts(draft))
    if not 1 <= part <= count:
        raise DocumentEditError(f"part {part} does not exist: the document has {count} PDFs")
    names = dict(draft.part_names)
    if name.strip():
        try:
            names[part] = sanitise_prefix(name)
        except InvalidPrefixError as error:
            raise DocumentEditError(str(error)) from error
    else:
        names.pop(part, None)
    return replace(draft, part_names=MappingProxyType(names))


def validate_edits(edits: PageEdits, page_count: int) -> None:
    """Raise DocumentEditError for edits that cannot be made to a document of ``page_count``
    pages: a page that is not there, a page both left out and brought back, a turn that is not
    1 to 3 quarter turns, an order that is not a permutation, a part number below 1."""
    mentioned = [*edits.drop, *edits.keep, *edits.rotate, *edits.split, *edits.colour]
    for number in sorted(mentioned):
        if not 1 <= number <= page_count:
            raise DocumentEditError(
                f"page {number} is not in the document, which has {page_count} pages"
            )
    for number in sorted(edits.drop & edits.keep):
        raise DocumentEditError(f"page {number} is in both the pages to drop and to keep")
    for number, turns in sorted(edits.rotate.items()):
        if not 1 <= turns < QUARTER_TURNS:
            raise DocumentEditError(f"page {number}: {turns} quarter turns is not an angle")
    if edits.order and sorted(edits.order) != list(range(1, page_count + 1)):
        raise DocumentEditError(
            f"the order must be a permutation of the page numbers 1 to {page_count}: "
            "every page exactly once"
        )
    for policy in edits.colour.values():
        _checked_colour(policy)
    for part in sorted(edits.part_names):
        if part < 1:
            raise DocumentEditError(f"part {part} does not exist: parts count from 1")


def with_edits(draft: DocumentDraft, edits: PageEdits) -> DocumentDraft:
    """``draft`` with all of ``edits`` made (turns are set, not added; splits are added). The
    order comes first, the part names last, because a part exists only once the rest is set."""
    validate_edits(edits, len(draft.pages))
    edited = _with_order(draft, edits.order) if edits.order else draft
    for number in sorted(edits.drop):
        edited = set_included(edited, number, False)
    for number in sorted(edits.keep):
        edited = set_included(edited, number, True)
    for number, turns in sorted(edits.rotate.items()):
        edit = edited.edits.get(number, PageEdit())
        edited = _with_page_edit(edited, number, replace(edit, quarter_turns=turns))
    for number, policy in sorted(edits.colour.items()):
        edited = set_colour(edited, number, policy)
    edited = replace(edited, splits=edited.splits | edits.split)
    for part, name in sorted(edits.part_names.items()):
        edited = set_part_name(edited, part, name)
    return edited


def parts(draft: DocumentDraft) -> tuple[OutputPart, ...]:
    """The PDFs the draft makes: the pages that stay, in output order, with their turns."""
    groups: list[list[tuple[PageAnalysis, int]]] = []
    pending_split = False
    for number in _order(draft):
        page = draft.pages[number - 1]
        pending_split = pending_split or number in draft.splits
        if not draft.is_included(page):
            continue
        if pending_split or not groups:
            if not groups or groups[-1]:
                groups.append([])
            pending_split = False
        turns = draft.edits.get(number, PageEdit()).quarter_turns
        groups[-1].append((page, turns))
    return tuple(
        OutputPart(tuple(group), draft.part_names.get(index))
        for index, group in enumerate(groups, start=1)
    )


def set_colour(draft: DocumentDraft, number: int, policy: ColourPolicy | None) -> DocumentDraft:
    """Return a draft with this raw page's policy override, or cleared with None."""
    _page(draft, number)
    _checked_colour(policy)
    edit = draft.edits.get(number, PageEdit())
    return _with_page_edit(draft, number, replace(edit, colour=policy))


def _checked_colour(policy: ColourPolicy | None) -> None:
    if policy is not None and not isinstance(policy, ColourPolicy):
        raise DocumentEditError("page colour mode must be Auto, colour, grey or black and white")
