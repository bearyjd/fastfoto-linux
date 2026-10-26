"""``ffscan doc process --dry-run``: what each page would become, and nothing written."""

from fastfoto_linux.documents.auto_colour import page_colour
from fastfoto_linux.documents.cleanup import page_cleanup
from fastfoto_linux.documents.draft import DocumentDraft, PageAnalysis, sorted_flags
from fastfoto_linux.documents.draft_edit import parts
from fastfoto_linux.documents.encode import effective_cleanup
from fastfoto_linux.documents.modes import CleanupPolicy, ColourMode, ColourPolicy

_COLUMNS = ("page", "verdict", "flags", "part", "what happens")
NO_PDF_LINE = "no PDF would be written: no page is left"


def _what_happens(draft: DocumentDraft, page: PageAnalysis, turns: int, starts_part: bool) -> str:
    edit = draft.edits.get(page.number)
    chosen = edit is not None and edit.include is not None
    if not draft.is_included(page):
        return "left out (you removed it)" if chosen else "left out (looks blank)"
    words = ["kept (brought back by you)" if chosen and page.blank else "kept"]
    if turns:
        words.append(f"turned {turns * 90}")
    if edit is not None and edit.crop is not None:
        words.append("cropped")
    if starts_part:
        words.append("starts a new PDF")
    return ", ".join(words)


def _rows(draft: DocumentDraft) -> list[tuple[str, ...]]:
    placed: dict[int, tuple[int, int, bool]] = {}
    for number, part in enumerate(parts(draft), start=1):
        for place, (page, turns) in enumerate(part.pages):
            placed[page.number] = (number, turns, place == 0 and number > 1)
    rows = []
    for page in draft.pages:
        number, turns, starts = placed.get(page.number, (0, 0, False))
        rows.append(
            (
                str(page.number),
                "blank" if page.blank else "kept",
                ",".join(sorted_flags(page.flags)) or "-",
                str(number) if number else "-",
                _what_happens(draft, page, turns, starts),
            )
        )
    return rows


def dry_run_lines(
    draft: DocumentDraft, policy: ColourPolicy | ColourMode = ColourMode.COLOUR
) -> list[str]:
    """The table (a header and a row for each page, in raw order), then a line for each PDF."""
    rows = _rows(draft)
    if policy == ColourPolicy.AUTO or any(edit.colour is not None for edit in draft.edits.values()):
        rows = [
            _colour_row(row, page, draft, policy)
            for row, page in zip(rows, draft.pages, strict=True)
        ]
    if draft.cleanup is not CleanupPolicy.OFF or any(
        edit.cleanup is not None for edit in draft.edits.values()
    ):
        rows = [
            _cleanup_row(row, page, draft, policy)
            for row, page in zip(rows, draft.pages, strict=True)
        ]
    table = [_COLUMNS, *rows]
    widths = [max(len(row[column]) for row in table) for column in range(len(_COLUMNS) - 1)]
    lines = [
        "  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=False))
        + "  "
        + row[-1]
        for row in table
    ]
    output = parts(draft)
    if not output:
        return [*lines, NO_PDF_LINE]
    for number, part in enumerate(output, start=1):
        count = len(part.pages)
        lines.append(f"PDF {number}: {count} page{'' if count == 1 else 's'}")
    return lines


def _colour_row(
    row: tuple[str, ...],
    page: PageAnalysis,
    draft: DocumentDraft,
    policy: ColourPolicy | ColourMode,
) -> tuple[str, ...]:
    mode = page_colour(draft, page, policy)
    reason = "" if page.colour is None else f" reason={page.colour.reason.value}"
    override = draft.edits.get(page.number)
    chosen = " override" if override is not None and override.colour is not None else ""
    return (*row[:-1], f"{row[-1]}; colour={mode.value}{reason}{chosen}")


def _cleanup_row(
    row: tuple[str, ...],
    page: PageAnalysis,
    draft: DocumentDraft,
    policy: ColourPolicy | ColourMode,
) -> tuple[str, ...]:
    """A kept page's row with the paper cleanup level the PDF will use (Off for black and white)."""
    if not draft.is_included(page):
        return row
    level = effective_cleanup(page_cleanup(draft, page), page_colour(draft, page, policy))
    override = draft.edits.get(page.number)
    chosen = " override" if override is not None and override.cleanup is not None else ""
    return (*row[:-1], f"{row[-1]}; cleanup={level.value}{chosen}")
