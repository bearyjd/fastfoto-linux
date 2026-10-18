"""Ink that comes from somewhere else: the other side of the paper, or a neighbouring sheet.

Both only explain a page that stays; neither drops or keeps one.

``show_through``: the paper is thin, so print on one side shows paler on the other, mirrored
(the back of a sheet is its front flipped left to right). A mark of a page shows through when
the other side has a darker shape at the mirrored spot (within ``holes.SHIFT_MM``, as for holes)
that overlaps it by ``SHOW_THROUGH_IOU`` or more (intersection over union of the two shapes,
each the pixels in the lighter half of its own darkest tone and white) and the mark is
``SHOW_THROUGH_PALER`` grey levels paler than that shape's darkest pixel. Print of the same
tone on both sides is not show-through. The page shows through when at least ``SHARE_MIN`` of
its marks do. This is the holes match without the tone floor (a ghost can be any grey) and
without the size limits (it is writing, not a hole).

``set_off``: ink rubbed off the printed side of a neighbouring sheet. A back whose marks lie
mirrored where a neighbouring sheet's printed side has marks (boxes overlapping by
``SET_OFF_IOU``, at least ``SHARE_MIN`` of the marks) is flagged. Boxes only: no pixels are held.
It is asked of backs with fewer marks than ``inkmap.MARKS_MIN`` (the ink map judges the rest),
and the boxes are compared in the scanner's frame (``frame_boxes``).
"""

from collections.abc import Sequence

import cv2
import numpy as np

from fastfoto_linux.documents.draft import BoxN, InkMap
from fastfoto_linux.documents.holes import SHIFT_MM, _comparable, _frame_width, _window
from fastfoto_linux.documents.loader import WHITE
from fastfoto_linux.documents.marks import Mark, darkest_channel
from fastfoto_linux.documents.trim import Trimmed
from fastfoto_linux.documents.units import mm_to_px

SHARE_MIN = 0.5  # at least this share of a page's marks must be explained
SHOW_THROUGH_IOU = 0.4  # a mark and its mirrored shape overlap by this share of their union
SHOW_THROUGH_PALER = 25  # the mark's darkest pixel is this much paler than the shape's
MAX_MARKS_COMPARED = 60  # a page with more marks than this is print: not compared (the ink map is)
SET_OFF_IOU = (
    0.3  # a mark's box and a neighbour's mirrored box overlap by this share of their union
)


def _ink(grey: np.ndarray) -> np.ndarray:
    """The pixels in the darker half between the darkest pixel of ``grey`` and white."""
    return grey < (int(grey.min()) + WHITE) // 2


def _best_overlap(template: np.ndarray, area: np.ndarray, reach: int) -> float:
    """The best intersection over union of ``template`` with ``area`` (a window ``reach`` bigger
    on every side), over every shift of up to ``reach`` pixels."""
    flat, patch = area.astype(np.float32), template.astype(np.float32)
    common = cv2.matchTemplate(flat, patch, cv2.TM_CCORR)
    under = cv2.matchTemplate(flat, np.ones_like(patch), cv2.TM_CCORR)
    union = float(patch.sum()) + under - common
    return float((common / np.maximum(union, 1.0)).max())


def _shows_through(mark: Mark, page: Trimmed, partner: Trimmed) -> bool:
    """Whether the other side has a darker shape at the mirrored spot of ``mark``."""
    reach = mm_to_px(SHIFT_MM, page.page.dpi)
    own = darkest_channel(page.page.pixels[mark.y0 : mark.y1, mark.x0 : mark.x1])
    height, width = own.shape
    left = _frame_width(page) - (mark.x0 + page.left + width) - partner.left
    top = mark.y0 + page.top - partner.top
    window = darkest_channel(
        _window(
            partner.page.pixels, left - reach, top - reach, (height + 2 * reach, width + 2 * reach)
        )
    )
    if int(own.min()) - int(window.min()) < SHOW_THROUGH_PALER:
        return False
    return _best_overlap(_ink(own)[:, ::-1], _ink(window), reach) >= SHOW_THROUGH_IOU


def show_through(marks: Sequence[Mark], page: Trimmed, partner: Trimmed) -> bool:
    """Whether most of the marks of ``page`` are paler, mirrored copies of the print of
    ``partner``, the other side of the same sheet."""
    if not marks or len(marks) > MAX_MARKS_COMPARED or not _comparable(page, partner):
        return False
    shown = sum(_shows_through(mark, page, partner) for mark in marks)
    return shown >= SHARE_MIN * len(marks)


def _iou(first: BoxN, second: BoxN) -> float:
    wide = min(first.x1, second.x1) - max(first.x0, second.x0)
    tall = min(first.y1, second.y1) - max(first.y0, second.y0)
    if wide <= 0 or tall <= 0:
        return 0.0
    common = wide * tall
    area = (first.x1 - first.x0) * (first.y1 - first.y0)
    other = (second.x1 - second.x0) * (second.y1 - second.y0)
    return common / (area + other - common)


def frame_boxes(marks: Sequence[BoxN], page: InkMap) -> tuple[BoxN, ...]:
    """The boxes of a page as shares of the scanner's frame (both axes over its width), the
    page's trim offsets added back, so that boxes of pages that lie differently in the frame
    can be compared. A sheet is assumed to lie in the frame as its neighbours do (a stack is fed
    the same way): the frame, not the paper, is what the mirror is taken in."""
    scale = page.frame_mm

    def shared(box: BoxN) -> BoxN:
        return BoxN(
            (page.left_mm + box.x0 * page.width_mm) / scale,
            (page.top_mm + box.y0 * page.height_mm) / scale,
            (page.left_mm + box.x1 * page.width_mm) / scale,
            (page.top_mm + box.y1 * page.height_mm) / scale,
        )

    return tuple(shared(box) for box in marks)


def _flipped(box: BoxN) -> BoxN:
    return BoxN(1.0 - box.x1, box.y0, 1.0 - box.x0, box.y1)


def set_off(marks: Sequence[BoxN], neighbours: Sequence[Sequence[BoxN]]) -> bool:
    """Whether most of the ``marks`` of a back, mirrored, overlap the mark boxes of the printed
    side of a neighbouring sheet (``neighbours``: the previous one's, the next one's)."""
    if not marks:
        return False
    printed = [box for boxes in neighbours for box in boxes]
    seen = sum(any(_iou(_flipped(mark), box) >= SET_OFF_IOU for box in printed) for mark in marks)
    return seen >= SHARE_MIN * len(marks)
