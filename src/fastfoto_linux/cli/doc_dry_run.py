"""``ffscan doc process --dry-run``: what each page would become, and nothing written."""

from fastfoto_linux.documents.draft import DocumentDraft, PageAnalysis, sorted_flags
from fastfoto_linux.documents.draft_edit import parts

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


def dry_run_lines(draft: DocumentDraft) -> list[str]:
    """The table (a header and a row for each page, in raw order), then a line for each PDF."""
    table = [_COLUMNS, *_rows(draft)]
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
