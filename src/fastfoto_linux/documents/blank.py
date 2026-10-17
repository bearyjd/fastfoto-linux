"""Decide whether a page is blank (a duplex back with nothing on it)."""

from fastfoto_linux.documents.loader import LoadedPage
from fastfoto_linux.documents.marks import find_marks
from fastfoto_linux.documents.trim import Trimmed

BLANK_MARGIN_MM = 5.0  # scanner shadows and edge marks live here; the margin is ignored


def is_blank(page: LoadedPage, *, trimmed_bottom: int = 0) -> bool:
    """True only when the page holds no mark at all inside its 5 mm margin.

    The margin belongs to the scanner's frame, not to the trimmed page: ``trimmed_bottom`` rows
    that were cut off the bottom (the tail) take their share of the margin with them, so
    trimming never turns paper into margin. A band cut leaves the paper's own edge: the caller
    passes ``Trimmed.tail_rows``, which is 0 then, and the margin is whole.

    One confident mark keeps the page, so a signature, a short line, or a page number alone is
    not blank. The one thing that is not a mark is a faint fold crease: a line, that is a mark
    that is straight, thin and elongated, with no dark part that would be a mark by itself and no
    other mark beside it (see ``find_marks``). Faint writing is never straight for long and has
    other strokes beside it, so it keeps the page; dark ink that touches a crease does too. When
    in doubt the answer is False.
    """
    return not find_marks(
        page, margin_mm=BLANK_MARGIN_MM, trimmed_bottom=trimmed_bottom, ignore_faint_lines=True
    )


def is_blank_beside(page: Trimmed, partner: Trimmed | None) -> bool:
    """Stub (red): ``is_blank``, whatever the partner."""
    return is_blank(page.page, trimmed_bottom=page.tail_rows)
