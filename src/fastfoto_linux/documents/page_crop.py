"""A reviewer's crop of a page, and the one sequence that turns a trimmed page into the edited one.

A crop is kept as whole units of a page's width and height (``CROP_UNITS`` of each), not as
pixels, so it stays inside the page when the page is analysed again with another trim box or
resolution. ``crop_box`` turns it back into pixels, rounding inward, and ``to_units`` rounds
outward, so a box drawn in pixels comes back as the same pixels. The preview and the PDF both
call ``edited_page``: crop first, then the quarter turns.
"""

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from fastfoto_linux.documents.loader import LoadedPage
from fastfoto_linux.documents.units import mm_to_px
from fastfoto_linux.photo_edits.geometry import apply_geometry
from fastfoto_linux.photo_edits.model import MIN_CROP_MM, PhotoGeometry

if TYPE_CHECKING:  # draft imports PageCrop from here
    from fastfoto_linux.documents.draft import PageEdit

CROP_UNITS = 10_000  # a page's width (or height) in crop units


@dataclass(frozen=True)
class PageCrop:
    """The part of the trimmed page to keep, half open, in units of 1/``CROP_UNITS`` of the
    page's width (left, right) and height (top, bottom)."""

    left: int
    top: int
    right: int
    bottom: int

    def __post_init__(self) -> None:
        edges = (self.left, self.top, self.right, self.bottom)
        if any(type(edge) is not int or not 0 <= edge <= CROP_UNITS for edge in edges):
            raise ValueError(f"crop edges must be whole numbers from 0 to {CROP_UNITS}")
        if self.left >= self.right or self.top >= self.bottom:
            raise ValueError("a crop must enclose an area")


def _axis(low: int, high: int, size: int, least: int) -> tuple[int, int]:
    """Pixels ``low`` to ``high`` units of a side of ``size`` pixels, rounded inward and grown
    (around their centre, kept inside the page) to ``least`` pixels when they are fewer."""
    start, stop = -(-low * size // CROP_UNITS), high * size // CROP_UNITS
    need = min(least, size)
    if stop - start >= need:
        return start, stop
    start = min(max((start + stop - need) // 2, 0), size - need)
    return start, start + need


def crop_box(width: int, height: int, dpi: int, crop: PageCrop) -> tuple[int, int, int, int]:
    """``crop`` as pixels (left, top, right, bottom) of a ``width`` x ``height`` page. Never
    raises: a side under ``MIN_CROP_MM`` (a page analysed again can be smaller) grows to it."""
    least = max(1, mm_to_px(MIN_CROP_MM, dpi))
    left, right = _axis(crop.left, crop.right, width, least)
    top, bottom = _axis(crop.top, crop.bottom, height, least)
    return left, top, right, bottom


def to_units(box: tuple[int, int, int, int], width: int, height: int) -> PageCrop:
    """A pixel box (left, top, right, bottom) of a ``width`` x ``height`` page as a ``PageCrop``,
    rounded outward. Raises ValueError for an empty box or one outside the page."""
    left, top, right, bottom = box
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        raise ValueError(f"the box {box} is empty or outside a {width} x {height} pixel page")
    return PageCrop(
        left * CROP_UNITS // width,
        top * CROP_UNITS // height,
        -(-right * CROP_UNITS // width),
        -(-bottom * CROP_UNITS // height),
    )


def edited_page(trimmed: LoadedPage, edit: "PageEdit") -> LoadedPage:
    """The trimmed page cut to the edit's crop, then turned clockwise by its quarter turns.
    With neither, ``trimmed`` itself; else new pixels (the input is not modified)."""
    if edit.crop is None and edit.quarter_turns == 0:
        return trimmed
    height, width = trimmed.pixels.shape[:2]
    box = None if edit.crop is None else crop_box(width, height, trimmed.dpi, edit.crop)
    geometry = PhotoGeometry(quarter_turns=edit.quarter_turns, crop=box)
    return replace(trimmed, pixels=apply_geometry(trimmed.pixels, geometry))
