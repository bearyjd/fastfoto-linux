"""Decide whether a page is blank (a duplex back with nothing on it)."""

from fastfoto_linux.documents.holes import all_are_holes
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
    """``is_blank`` for a page whose sheet's other side is ``partner`` (None: it has none).

    A page is also blank when every mark on it is a hole through the paper that ``partner``
    shows too: at most ``holes.HOLE_MAX_MM`` (8 mm) long, within ``holes.EDGE_ZONE_MM`` (25 mm)
    of an edge, neutral grey (blue less red within 12, darkest pixel 60 or paler: print is
    darker), and matched on the other side at the mirrored spot within ``holes.SHIFT_MM`` (2.0 mm)
    by a shape of the same size and grey (darkest pixel within 30 of the other's) that overlaps it
    by ``holes.MATCH_IOU`` (0.5) or more, with all the holes of the page within 0.5 mm of one
    registration (see ``holes``; a mark's shape is its whole dark shape, even where the blank
    margin cuts the mark short, and one longer than 8 mm is not a hole). Without a partner nothing
    is a hole, and the answer is that of ``is_blank``.
    A mark that is not a hole keeps the page, as ever; when in doubt the answer is False.
    """
    marks = find_marks(
        page.page,
        margin_mm=BLANK_MARGIN_MM,
        trimmed_bottom=page.tail_rows,
        ignore_faint_lines=True,
    )
    return not marks or (partner is not None and all_are_holes(marks, page, partner))
