"""Flags that need the other pages of the document, settled once every sheet is analysed.

Only the boxes and the coarse ink maps of the pages are used (no pixels are held). A kept back
is ``SET_OFF`` when its marks lie where the previous or the next sheet's front is printed
(``inkmap.lies_on``, from ``MARKS_MIN`` marks) or, with fewer marks, when their boxes mirror
that front's (``bleed.set_off``, in the scanner's frame); the page's ``detail`` then says
``set_off_next`` or ``set_off_prev``. It is ``SHOW_THROUGH`` when its marks lie where its own
front is printed. Neighbouring sheets are assumed to lie in the frame alike.
"""

from dataclasses import replace

from fastfoto_linux.documents.bleed import frame_boxes, set_off
from fastfoto_linux.documents.draft import BoxN, Flag, PageAnalysis
from fastfoto_linux.documents.inkmap import MARKS_MIN, lies_on

SHEET_SIDES = 2  # a front and a back; the previous sheet's front is this many pages and one back


def _kept_back(page: PageAnalysis) -> bool:
    return page.partner is not None and page.partner < page.number and not page.blank


def _lies_on(page: PageAnalysis, source: PageAnalysis | None) -> bool:
    return (
        source is not None
        and source.ink is not None
        and page.ink is not None
        and lies_on(page.marks, page.ink, source.ink)
    )


def _boxes(page: PageAnalysis) -> tuple[BoxN, ...]:
    return page.marks if page.ink is None else frame_boxes(page.marks, page.ink)


def _set_off_by(page: PageAnalysis, source: PageAnalysis | None) -> bool:
    """Whether the few marks of ``page`` mirror the boxes of ``source``, a neighbour's front."""
    return (
        source is not None
        and 0 < len(page.marks) < MARKS_MIN
        and set_off(_boxes(page), [_boxes(source)])
    )


def _settled(page: PageAnalysis, by_number: dict[int, PageAnalysis]) -> PageAnalysis:
    """``page`` with the flags that come from the pages round it."""
    if not _kept_back(page) or not page.marks:
        return page
    flags: set[Flag] = set()
    detail: list[str] = []
    own = None if page.partner is None else by_number.get(page.partner)
    if _lies_on(page, own):
        flags.add(Flag.SHOW_THROUGH)
    for name, number in (("next", page.number + 1), ("prev", page.number - SHEET_SIDES - 1)):
        source = by_number.get(number)
        if _lies_on(page, source) or _set_off_by(page, source):
            flags.add(Flag.SET_OFF)
            detail.append(f"set_off_{name}")
    if not flags:
        return page
    return replace(page, flags=page.flags | flags, detail=page.detail + tuple(detail))


def with_neighbour_flags(pages: list[PageAnalysis]) -> list[PageAnalysis]:
    """The pages with the flags that depend on the pages next to them."""
    by_number = {page.number: page for page in pages}
    return [_settled(page, by_number) for page in pages]
