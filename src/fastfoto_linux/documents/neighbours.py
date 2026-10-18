"""Flags that need the other pages of the document, settled once every sheet is analysed.

Only the boxes and the coarse ink maps of the pages are used (no pixels are held). A kept back
is ``SET_OFF`` when its mark boxes mirror those of the previous or the next sheet's front
(``bleed.set_off``), or when its marks lie where that front is printed (``inkmap.lies_on``;
the page's ``detail`` then says ``set_off_next`` or ``set_off_prev``); it is ``SHOW_THROUGH``
when they lie where its own front is printed.
"""

from dataclasses import replace

from fastfoto_linux.documents.assess import MAX_BOXES
from fastfoto_linux.documents.bleed import set_off
from fastfoto_linux.documents.draft import Flag, PageAnalysis
from fastfoto_linux.documents.inkmap import lies_on

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


def _settled(page: PageAnalysis, by_number: dict[int, PageAnalysis]) -> PageAnalysis:
    """``page`` with the flags that come from the pages round it."""
    if not _kept_back(page) or not page.marks:
        return page
    previous = by_number.get(page.number - SHEET_SIDES - 1)
    following = by_number.get(page.number + 1)
    flags: set[Flag] = set()
    detail: list[str] = []
    if 0 < len(page.marks) < MAX_BOXES and set_off(
        page.marks, [other.marks for other in (previous, following) if other is not None]
    ):
        flags.add(Flag.SET_OFF)
    if page.partner is not None and _lies_on(page, by_number.get(page.partner)):
        flags.add(Flag.SHOW_THROUGH)
    for name, source in (("next", following), ("prev", previous)):
        if _lies_on(page, source):
            flags.add(Flag.SET_OFF)
            detail.append(f"set_off_{name}")
    if not flags:
        return page
    return replace(page, flags=page.flags | flags, detail=page.detail + tuple(detail))


def with_neighbour_flags(pages: list[PageAnalysis]) -> list[PageAnalysis]:
    """The pages with the flags that depend on the pages next to them."""
    by_number = {page.number: page for page in pages}
    return [_settled(page, by_number) for page in pages]
