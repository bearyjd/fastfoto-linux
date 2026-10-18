"""Edits to a draft as pure functions: each returns a new draft and never changes its input."""

from collections.abc import Mapping
from dataclasses import dataclass, field

from fastfoto_linux.documents.draft import DocumentDraft, OutputPart


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


def set_included(draft: DocumentDraft, number: int, keep: bool) -> DocumentDraft:
    raise NotImplementedError


def rotate(draft: DocumentDraft, number: int, turns: int) -> DocumentDraft:
    raise NotImplementedError


def move(draft: DocumentDraft, number: int, to_index: int) -> DocumentDraft:
    raise NotImplementedError


def toggle_split(draft: DocumentDraft, number: int) -> DocumentDraft:
    raise NotImplementedError


def set_part_name(draft: DocumentDraft, part: int, name: str) -> DocumentDraft:
    raise NotImplementedError


def validate_edits(edits: PageEdits, page_count: int) -> None:
    raise NotImplementedError


def with_edits(draft: DocumentDraft, edits: PageEdits) -> DocumentDraft:
    raise NotImplementedError


def parts(draft: DocumentDraft) -> tuple[OutputPart, ...]:
    raise NotImplementedError
