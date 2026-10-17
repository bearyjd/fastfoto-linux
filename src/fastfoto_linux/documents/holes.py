"""Holes through the paper: a small dark mark on one side that the other side shows too.

A staple, a punch or a clip leaves a hole, and the dark backing shows through it on both sides of
the sheet. A back that is otherwise empty would be kept for those marks, so on a duplex sheet a
counted mark (see ``find_marks``) is a hole when all of this holds:

* its longer side is at most ``HOLE_MAX_MM`` (punched holes are about 6 mm, staple holes 1 to 2),
* it lies within ``EDGE_ZONE_MM`` of an edge of the page, and
* the other side of the same sheet has a matching dark shape at the mirrored spot.

The back of a sheet is its front flipped left to right and the top stays on top, so a spot that is
``x`` from the left of the scanner's frame on one side is ``frame width - x`` on the other, at the
same ``y``. Both are taken in the scanner's frame, with the offsets of each side's trim added back.
The shapes are the pixels darker than ``HOLE_TONE`` on the darkest colour channel. They match when
the other side has a whole dark shape of the same size (each of its two sides within a factor of
``SIZE_RATIO``; a big dark area under a small mark is not a hole) and, shifted by at most
``SHIFT_MM`` in either direction (the sides line up to about 1.2 mm: the feeder, the deskew, the
trim), the two overlap by at least ``MATCH_IOU`` (intersection over union). One shape explains one
mark: two marks beside each other do not both match the one mark opposite.

Limits: the same symmetric mark printed at the mirrored spots of both sides, near an edge of an
otherwise blank back, is taken for a hole; and the pairing is by page order, so pages that do not
start with a front are paired wrongly (a back then meets another front, and is kept unless that
front has a shape at the mirrored spot too, as a stapled stack has).
"""

from collections.abc import Sequence
from dataclasses import dataclass

import cv2
import numpy as np

from fastfoto_linux.documents.loader import LoadedPage
from fastfoto_linux.documents.marks import Mark
from fastfoto_linux.documents.trim import Trimmed
from fastfoto_linux.documents.units import MM_PER_INCH, mm_to_px
from fastfoto_linux.imaging import RGB_NDIM

HOLE_MAX_MM = 8.0  # a hole is no longer than this: punched holes about 6 mm, staple holes 1 to 2
EDGE_ZONE_MM = 25.0  # staples, clips and punches sit this near an edge of the page, or nearer
SHIFT_MM = 2.0  # the mirrored spot is searched this far to each side
MATCH_IOU = 0.5  # the two shapes overlap by at least this share of their union
SIZE_RATIO = 1.5  # each side of the other shape's box is within this factor of the mark's
HOLE_TONE = 160  # a pixel darker than this (darkest colour channel) is part of a dark shape

_Key = tuple[int, int]  # where a shape lies on the other side: its box's top left corner


@dataclass(frozen=True)
class _Shape:
    """The dark pixels of a mark, cropped to their box, and where the box's top left corner lies
    in the pixels of its page."""

    mask: np.ndarray
    x: int
    y: int

    @property
    def sides(self) -> tuple[int, int]:
        """The short and the long side of the box in pixels."""
        short, long = sorted(self.mask.shape)
        return short, long


def _dark(pixels: np.ndarray) -> np.ndarray:
    grey = pixels.min(axis=2) if pixels.ndim == RGB_NDIM else pixels
    return grey < HOLE_TONE


def _mm(pixels: int, dpi: int) -> float:
    return pixels * MM_PER_INCH / dpi


def _could_be_hole(mark: Mark, page: LoadedPage) -> bool:
    """Whether a mark is small enough, and near enough to an edge, to be a hole."""
    height, width = page.pixels.shape[:2]
    longer = max(mark.x1 - mark.x0, mark.y1 - mark.y0)
    edge = min(mark.x0, mark.y0, width - mark.x1, height - mark.y1)
    return _mm(longer, page.dpi) <= HOLE_MAX_MM and _mm(edge, page.dpi) <= EDGE_ZONE_MM


def _shape_of(page: LoadedPage, mark: Mark) -> _Shape | None:
    """The dark pixels in the box of ``mark``; None when it holds none (a mark that is only
    pale cannot be the dark backing seen through a hole)."""
    crop = _dark(page.pixels[mark.y0 : mark.y1, mark.x0 : mark.x1])
    rows, columns = np.nonzero(crop)
    if len(rows) == 0:
        return None
    top, left = int(rows.min()), int(columns.min())
    tight = crop[top : int(rows.max()) + 1, left : int(columns.max()) + 1]
    return _Shape(tight, mark.x0 + left, mark.y0 + top)


def _frame_width(side: Trimmed) -> int:
    return side.page.pixels.shape[1] + side.left + side.right


def _comparable(side: Trimmed, partner: Trimmed) -> bool:
    """Whether two sides share a resolution and a scanner frame (as the sides of one sheet do)."""
    if side.page.dpi != partner.page.dpi:
        return False
    return abs(_frame_width(side) - _frame_width(partner)) <= mm_to_px(SHIFT_MM, side.page.dpi)


def _mirrored(shape: _Shape, side: Trimmed, partner: Trimmed) -> _Key:
    """Where the top left corner of ``shape`` lies in the pixels of the partner once the frame
    is flipped left to right: x becomes the frame width less x (less the shape's own width, for
    its corner), y stays; each side's trim offsets are added back and taken off again."""
    frame_x = shape.x + side.left + shape.mask.shape[1]
    return _frame_width(side) - frame_x - partner.left, shape.y + side.top - partner.top


def _canvas(pixels: np.ndarray, left: int, top: int, size: tuple[int, int]) -> np.ndarray:
    """The dark pixels of the ``size`` (height, width) area at (``left``, ``top``) of a page;
    where the area leaves the page there is nothing dark."""
    height, width = size
    canvas = np.zeros(size, dtype=bool)
    first_x, first_y = max(left, 0), max(top, 0)
    last_x = min(left + width, pixels.shape[1])
    last_y = min(top + height, pixels.shape[0])
    if last_x > first_x and last_y > first_y:
        canvas[first_y - top : last_y - top, first_x - left : last_x - left] = _dark(
            pixels[first_y:last_y, first_x:last_x]
        )
    return canvas


def _same_size(first: tuple[int, int], second: tuple[int, int]) -> bool:
    return all(max(a, b) <= SIZE_RATIO * min(a, b) for a, b in zip(first, second, strict=True))


def _overlap(template: np.ndarray, shape: np.ndarray, pad: int, reach: int) -> float:
    """The best intersection over union of ``template`` with ``shape`` over every shift of up to
    ``reach`` pixels from the spot ``pad`` pixels in from the corner of the canvas of ``shape``."""
    common = cv2.matchTemplate(shape.astype(np.float32), template.astype(np.float32), cv2.TM_CCORR)
    near = np.rint(common[pad - reach : pad + reach + 1, pad - reach : pad + reach + 1])
    union = int(template.sum()) + int(shape.sum()) - near
    return float((near / union).max())


def _counterpart(shape: _Shape, side: Trimmed, partner: Trimmed, taken: set[_Key]) -> _Key | None:
    """The dark shape on the partner's side that matches ``shape`` at the mirrored spot and has
    not explained another mark yet, the best overlap first; None when there is none."""
    dpi = side.page.dpi
    reach = mm_to_px(SHIFT_MM, dpi)
    pad = reach + mm_to_px(HOLE_MAX_MM * SIZE_RATIO, dpi)
    height, width = shape.mask.shape
    x, y = _mirrored(shape, side, partner)
    canvas = _canvas(partner.page.pixels, x - pad, y - pad, (height + 2 * pad, width + 2 * pad))
    template = shape.mask[:, ::-1]
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        canvas.astype(np.uint8), connectivity=8
    )
    best: tuple[float, _Key] | None = None
    for label in range(1, count):
        left, top, wide, tall, _ = stats[label].tolist()
        key = (left + x - pad, top + y - pad)
        touches_edge = left == 0 or top == 0 or left + wide == canvas.shape[1]
        touches_edge = touches_edge or top + tall == canvas.shape[0]
        if touches_edge or key in taken or not _same_size(shape.sides, tuple(sorted((tall, wide)))):
            continue
        overlap = _overlap(template, labels == label, pad, reach)
        if overlap >= MATCH_IOU and (best is None or overlap > best[0]):
            best = (overlap, key)
    return None if best is None else best[1]


def all_are_holes(marks: Sequence[Mark], side: Trimmed, partner: Trimmed) -> bool:
    """Whether every mark of ``side`` is a hole through the paper that ``partner``, the other
    side of the same sheet, shows too (see the module's text). No marks is not a hole: the
    caller has already called that page blank."""
    page = side.page
    if not marks or not _comparable(side, partner):
        return False
    if not all(_could_be_hole(mark, page) for mark in marks):
        return False
    taken: set[_Key] = set()
    for mark in marks:
        shape = _shape_of(page, mark)
        found = None if shape is None else _counterpart(shape, side, partner, taken)
        if found is None:
            return False
        taken.add(found)
    return True
