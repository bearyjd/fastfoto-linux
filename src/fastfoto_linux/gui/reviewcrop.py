"""The hand crop of the previewed page: from a drag or from units, and the box to draw.

Kept out of ``reviewside`` (its size). Nothing here raises: a refused crop returns False, and a
crop that cannot be stored says so in words that carry no page or box dimensions.
"""

from typing import TYPE_CHECKING

from fastfoto_linux.documents.draft_edit import DocumentEditError
from fastfoto_linux.documents.page_crop import PageCrop
from fastfoto_linux.gui.doccropcoords import crop_rect, drag_to_crop

if TYPE_CHECKING:
    from fastfoto_linux.gui.reviewside import ReviewSide

CROP_FAILED = "The page could not be cropped."


def crop_from_drag(  # noqa: PLR0913, PLR0917 - the drag and the painted geometry, passed through
    side: "ReviewSide",
    number: int,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    *,
    painted_width: float,
    painted_height: float,
    item_width: float,
    item_height: float,
) -> bool:
    """Store the crop a drag on the source preview of page ``number`` covers.

    False (nothing stored) when that page's source preview is not showing or the drag is under
    5 mm on a side or unusable.
    """
    if not _source_ready(side, number):
        return False
    crop = drag_to_crop(
        x0,
        y0,
        x1,
        y1,
        size=side.preview_size,
        dpi=side.preview_dpi,
        painted_width=painted_width,
        painted_height=painted_height,
        item_width=item_width,
        item_height=item_height,
    )
    return crop is not None and _edit(side, number, crop)


def store_crop(side: "ReviewSide", number: int, *edges: int) -> bool:
    """Store the crop of ``edges`` (left, top, right, bottom, in page units) for page ``number``."""
    try:
        crop = PageCrop(*edges)
    except (TypeError, ValueError):
        return _refused(side)
    return _edit(side, number, crop)


def clear_crop(side: "ReviewSide", number: int) -> bool:
    return _edit(side, number, None)


def crop_rectangle(side: "ReviewSide") -> list[int]:
    """The previewed page's crop as pixels of its source preview; [] when none or unknown."""
    number = side.preview_number
    if side.state is None or not _source_ready(side, number):
        return []
    crop = side.state.draft.edits.get(number)
    if crop is None or crop.crop is None:
        return []
    return list(crop_rect(crop.crop, side.preview_size, side.preview_dpi))


def _source_ready(side: "ReviewSide", number: int) -> bool:
    return bool(
        side.active
        and side.preview_view == "source"
        and side.preview_path is not None
        and side.preview_number == number
        and side.preview_size is not None
        and side.preview_dpi is not None
    )


def _edit(side: "ReviewSide", number: int, crop: PageCrop | None) -> bool:
    try:
        return side.edit("set_crop", number, crop)
    except DocumentEditError:
        return _refused(side)


def _refused(side: "ReviewSide") -> bool:
    side.report_error(CROP_FAILED)
    return False
