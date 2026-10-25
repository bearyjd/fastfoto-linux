"""Immutable review state, page rows and explanatory words, independent of Qt."""

from dataclasses import dataclass, replace
from pathlib import Path

from fastfoto_linux.documents import draft_edit
from fastfoto_linux.documents.auto_colour import ColourReason, page_policy, resolve_colour
from fastfoto_linux.documents.cleanup import CleanupStatus, page_cleanup
from fastfoto_linux.documents.draft import (
    BoxN,
    DocumentDraft,
    Flag,
    PageAnalysis,
    PageEdit,
    sorted_flags,
)
from fastfoto_linux.documents.draft_store import THUMBS_DIR
from fastfoto_linux.documents.modes import CleanupPolicy, ColourMode, ColourPolicy

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

    def set_colour(self, number: int, policy: ColourPolicy | None) -> "ReviewState":
        return replace(self, draft=draft_edit.set_colour(self.draft, number, policy))

    def set_cleanup(self, number: int, policy: CleanupPolicy | None) -> "ReviewState":
        return replace(self, draft=draft_edit.set_cleanup(self.draft, number, policy))

    def set_document_cleanup(self, policy: CleanupPolicy) -> "ReviewState":
        return replace(self, draft=draft_edit.set_document_cleanup(self.draft, policy))

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
    colour_policy: str = "colour"
    colour_mode: str = ""
    colour_reason: str = ""
    colour_override: str = ""
    colour_text: str = ""
    cleanup_override: str = ""
    cleanup_text: str = ""


MODE_LABELS = {"colour": "Colour", "grey": "Grey", "bw": "Black and white"}
REASON_LABELS = {
    ColourReason.SOURCE_BW: "black and white source",
    ColourReason.COLOUR_MARKS: "colour marks",
    ColourReason.COLOUR_UNCERTAIN: "possible colour",
    ColourReason.CONTINUOUS_TONE: "continuous tones",
    ColourReason.FAINT_MARKS: "faint marks",
    ColourReason.THRESHOLD_RISK: "preserve shading and fine marks",
    ColourReason.BILEVEL: "clear dark marks on light paper",
}

CLEANUP_SKIP_LABELS = {
    CleanupStatus.DARK: "paper too dark",
    CleanupStatus.STOCK: "coloured paper preserved",
    CleanupStatus.NO_PAPER: "no paper detected",
    CleanupStatus.TOO_LARGE: "page exceeds cleanup size limit",
    CleanupStatus.BW: "black and white output",
    CleanupStatus.OFF: "cleanup off",
}


def preview_cleanup_text(level: CleanupPolicy, status: CleanupStatus | None) -> str:
    """Describe worker results; legacy previews without metadata leave the result unknown."""
    if status is CleanupStatus.APPLIED:
        return f"paper cleanup {level.value.capitalize()} applied"
    if status is not None:
        return f"paper cleanup skipped: {CLEANUP_SKIP_LABELS[status]}"
    return f"paper cleanup {level.value.capitalize()} requested (result unavailable)"


def colour_values(
    draft: DocumentDraft, page: PageAnalysis, document_policy: ColourPolicy | ColourMode
) -> tuple[str, str, str, str, str]:
    """Present stored decisions; never read or classify full raw pages on the GUI thread."""
    policy = page_policy(draft, page, document_policy)
    edit = draft.edits.get(page.number, PageEdit())
    override = edit.colour.value if edit.colour is not None else ""
    if page.colour is None:
        label = "Auto" if policy is ColourPolicy.AUTO else MODE_LABELS[policy.value]
        return policy.value, "", "", override, f"{label}: awaiting page analysis"
    mode = resolve_colour(page.colour, policy)
    reason = page.colour.reason
    text = MODE_LABELS[mode.value]
    if policy is ColourPolicy.AUTO:
        text = f"Auto: {text} — {REASON_LABELS[reason]}"
    return policy.value, mode.value, reason.value, override, text


def cleanup_values(draft: DocumentDraft, page: PageAnalysis, resolved_mode: str) -> tuple[str, str]:
    """The page's own paper cleanup choice ("" when it follows the document) and its words."""
    edit = draft.edits.get(page.number, PageEdit())
    override = edit.cleanup.value if edit.cleanup is not None else ""
    if resolved_mode == ColourMode.BW.value:
        return override, "Paper cleanup: not used for black and white output"
    level = page_cleanup(draft, page)
    if level is CleanupPolicy.OFF:
        return override, "Paper cleanup: off"
    source = "this page" if edit.cleanup is not None else "document setting"
    return override, f"Paper cleanup: {level.value.capitalize()} requested ({source})"


def review_items(
    state: ReviewState, document_policy: ColourPolicy | ColourMode = ColourPolicy.COLOUR
) -> tuple[ReviewItem, ...]:
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
        colour = colour_values(draft, page, document_policy)
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
                *colour,
                *cleanup_values(draft, page, colour[1]),
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
