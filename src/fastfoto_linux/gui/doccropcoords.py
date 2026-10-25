"""A drag on the painted page as a crop in page units, and a crop as the box to draw."""

from fastfoto_linux.documents.page_crop import PageCrop, crop_box, to_units
from fastfoto_linux.documents.units import mm_to_px
from fastfoto_linux.gui.photoeditcoords import source_crop
from fastfoto_linux.photo_edits.model import MIN_CROP_MM


def drag_to_crop(  # noqa: PLR0913 - dimensions describe one explicit transform
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    *,
    size: tuple[int, int],
    dpi: int,
    painted_width: float,
    painted_height: float,
    item_width: float,
    item_height: float,
) -> PageCrop | None:
    """The crop a drag covers on the trimmed, unturned page of ``size`` pixels, or None when it
    is under ``MIN_CROP_MM`` on a side or any number is unusable."""
    width, height = size
    if type(dpi) is not int or dpi <= 0 or width <= 0 or height <= 0:
        return None
    least = max(1, mm_to_px(MIN_CROP_MM, dpi))
    box = source_crop(
        x0,
        y0,
        x1,
        y1,
        min_width=least,
        min_height=least,
        source_width=width,
        source_height=height,
        painted_width=painted_width,
        painted_height=painted_height,
        item_width=item_width,
        item_height=item_height,
    )
    return None if box is None else to_units(box, width, height)


def crop_rect(crop: PageCrop, size: tuple[int, int], dpi: int) -> tuple[int, int, int, int]:
    """The pixel box (left, top, right, bottom) of the page that ``crop`` keeps: what is written."""
    return crop_box(size[0], size[1], dpi, crop)
