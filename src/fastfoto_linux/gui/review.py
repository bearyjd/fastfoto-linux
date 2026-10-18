"""Immutable review state, page rows and explanatory words, independent of Qt."""

from dataclasses import dataclass, replace
from pathlib import Path

from fastfoto_linux.documents import draft_edit
from fastfoto_linux.documents.draft import (
    BoxN,
    DocumentDraft,
    Flag,
    PageAnalysis,
    PageEdit,
    sorted_flags,
)
from fastfoto_linux.documents.draft_store import THUMBS_DIR

FLAG_LABELS = {
    Flag.FEW_MARKS: "Only a few marks",
    Flag.EDGE_ONLY: "Marks near the edges",
    Flag.HOLE_LIKE: "Possible staple holes",
    Flag.FAINT_ONLY: "Only faint marks",
    Flag.SHOW_THROUGH: "Possible show-through from the other side",
    Flag.SET_OFF: "Possible offset from a neighbouring sheet",
    Flag.CREASE_IGNORED: "Faint crease ignored",
    Flag.HOLES_MATCHED: "Staple holes match the other side",
}


@dataclass(frozen=True)
class ReviewState:
    """A draft and the user's view of it; every operation returns a new value."""

    draft: DocumentDraft
    focus: int = 1
    flagged_only: bool = False

    def toggle(self, number: int) -> "ReviewState":
        page = self._page(number)
        return replace(
            self,
            draft=draft_edit.set_included(self.draft, number, not self.draft.is_included(page)),
        )

    def rotate(self, number: int, turns: int) -> "ReviewState":
        return replace(self, draft=draft_edit.rotate(self.draft, number, turns))

    def move(self, number: int, to: int) -> "ReviewState":
        return replace(self, draft=draft_edit.move(self.draft, number, to))

    def toggle_split(self, number: int) -> "ReviewState":
        return replace(self, draft=draft_edit.toggle_split(self.draft, number))

    def name_part(self, number: int, name: str) -> "ReviewState":
        return replace(self, draft=draft_edit.set_part_name(self.draft, number, name))

    def only_flagged(self, enabled: bool) -> "ReviewState":
        return replace(self, flagged_only=enabled)

    def focused(self, number: int) -> "ReviewState":
        self._page(number)
        return replace(self, focus=number)

    def _page(self, number: int) -> PageAnalysis:
        if not 1 <= number <= len(self.draft.pages):
            raise ValueError(f"page {number} does not exist")
        return self.draft.pages[number - 1]


@dataclass(frozen=True)
class ReviewItem:
    number: int
    order_index: int
    thumb: Path | None
    included: bool
    turns: int
    flags: tuple[str, ...]
    flag_text: str
    marks: tuple[BoxN, ...]
    starts_part: bool
    part: int
    dropped: bool


def review_items(state: ReviewState) -> tuple[ReviewItem, ...]:
    """All raw pages in review order, including the pages that do not go into a PDF."""
    draft = state.draft
    output = draft_edit.parts(draft)
    part_numbers = {
        page.number: number for number, part in enumerate(output, 1) for page, _turns in part.pages
    }
    starts = {part.pages[0][0].number for part in output[1:]}
    rows = []
    for order_index, number in enumerate(draft.order or tuple(range(1, len(draft.pages) + 1))):
        page = draft.pages[number - 1]
        if state.flagged_only and not page.flags:
            continue
        included = draft.is_included(page)
        thumb = draft.raw_dir / THUMBS_DIR / page.thumb if draft.raw_dir and page.thumb else None
        flags = sorted_flags(page.flags)
        rows.append(
            ReviewItem(
                number,
                order_index,
                thumb,
                included,
                draft.edits.get(number, PageEdit()).quarter_turns,
                tuple(str(flag) for flag in flags),
                "; ".join(FLAG_LABELS[flag] for flag in flags),
                page.marks,
                number in starts,
                part_numbers.get(number, 0),
                page.blank and not included,
            )
        )
    return tuple(rows)


def review_summary(state: ReviewState) -> str:
    draft = state.draft
    count = len(draft_edit.parts(draft))
    removed = sum(not draft.is_included(page) for page in draft.pages)
    flagged = sum(bool(page.flags) for page in draft.pages)
    pdfs = "PDF" if count == 1 else "PDFs"
    return f"{len(draft.pages)} pages → {count} {pdfs} · {removed} removed · {flagged} to check"
