"""Holes through the paper: a small dark mark on one side that the other side shows too.

A staple, a punch or a clip leaves a hole, and the dark backing shows through it on both sides of
the sheet. A back that is otherwise empty would be kept for those marks, so on a duplex sheet a
counted mark (see ``find_marks``) is a hole when all of this holds:

* its whole shape is the size of a staple hole or of a punched hole: at most ``STAPLE_MAX_MM`` long
  (real staple holes: 0.6 to 1.35 mm), or a round disc ``PUNCH_MIN_MM`` to ``HOLE_MAX_MM`` long
  (punched holes are about 6 mm) whose box has a short side at least ``PUNCH_ASPECT_MIN`` of its
  long one and is at least ``PUNCH_FILL_MIN`` filled (a disc fills 0.78). Anything in between, and a
  long thin or hollow mark over 1.8 mm (a "0", an "o" of print), is never a hole,
* it lies within ``EDGE_ZONE_MM`` of an edge of the page,
* it is grey and neutral, and the other side shows the same grey (below), and
* the other side of the same sheet has a matching dark shape, of a hole's size too, at the
  mirrored spot.

Black print is never a hole. The backing seen through a hole is dark grey (real holes: darkest pixel
89 to 106, the two sides at most 15 apart, mean blue less red at most 4); print and ink are black or
coloured (print: darkest 0 to 12). So the darkest pixel of a hole is no darker than
``HOLE_DARKEST_MIN`` on both sides, the two sides' darkest pixels are within ``HOLE_TONE_MATCH`` of
each other (a dark stamp is not its own pale ghost), and the mean blue less red of its shape is
within ``HOLE_TINT`` of 0 (blue and red ink are not holes), so black print, pen, stamps and ink of a
colour are not holes. Print in a grey as light as the backing is told by its size and shape. A page
number in Arabic digits set at 8 pt or more in a proportional Sans or Serif font has digits 2 to 3
mm tall (tested at 8 to 12 pt), over a staple hole, and not round discs, so in no grey is it a hole.
A 1-bit page has no greys (a hole is as black as print), so on one nothing is a hole.

The back of a sheet is its front flipped left to right and the top stays on top, so a spot that is
``x`` from the left of the scanner's frame on one side is ``frame width - x`` on the other, at the
same ``y``. Both are taken in the scanner's frame, with the offsets of each side's trim added back.
The shapes are the pixels darker than ``HOLE_TONE`` on the darkest colour channel. A mark's shape is
the whole dark shape that meets its box, cropped to its own bounding box, not clipped by the box or
by the blank margin (a hole that straddles the margin is counted only where it lies inside, and goes
on beyond its box); one that is not a hole's size is not a hole, so a small mark joined to a long
dark line is content. They match when the other side has a whole dark shape of the same size (each
of its two sides within a factor of ``SIZE_RATIO``; a big dark area under a small mark is not a
hole) and, shifted by at most ``SHIFT_MM`` in either direction (the sides line up to about 1.2 mm:
the feeder, the deskew, the trim), the two overlap by at least ``MATCH_IOU`` (intersection over
union). One shape explains one mark: two marks beside each other do not both match the one mark
opposite.

The offset of a hole is where its counterpart lies from the mirrored spot (centre to centre). The
holes of a sheet share one registration (real holes: within 0.1 mm of each other), so when a page
has two or more, their offsets agree within ``OFFSET_SPREAD_MM`` on each axis; marks that only look
alike land at arbitrary offsets inside the window. The window is ``SHIFT_MM``, and a hole is found
as far out as its overlap allows, so a bigger hole is found further: measured, up to 2.5 mm for a
staple hole of 1.8 mm and up to 3.5 mm for a punched hole of 6 mm.

Limits: pencil and grey marks rely on size, shape, tint and registration only: the same symmetric
mark at the mirrored spots of both sides, near an edge of an otherwise blank back, is taken for a
hole, and that includes smaller grey marks, a grey "." or "-" or "o" of pencil or of grey print (a
whole shape of at most 1.8 mm, as the digits of a numeral set under 8 pt can be) at the mirrored
spot of a grey mark on the other side, and grey glyphs only x-height tall, lowercase roman folios
such as "x", "v" and "o", up to about 9 pt in Sans or 11 pt in Serif, at the mirrored spot of a
similar grey glyph on a grey front (as measured, "ix" on the front and "x" on the back), and grey
monospace digits at 8 to 9 pt, each of which drops only the lone folio of an otherwise blank back; a
rotation between the sides spreads the offsets of holes in proportion to the distance between them,
so holes 216 mm apart (a three-hole punch on Letter paper) are holes only while the sides are within
about 0.15 degrees of each other, and staple holes close together are not affected (beyond that the
page is kept, the safe side); and the pairing is by page order, so pages that do not start with a
front are paired wrongly (a back then meets another front, and is kept unless that front has a shape
at the mirrored spot too, as a stapled stack has).
"""

from collections.abc import Sequence
from dataclasses import dataclass

import cv2
import numpy as np

from fastfoto_linux.documents.loader import WHITE, LoadedPage
from fastfoto_linux.documents.marks import Mark
from fastfoto_linux.documents.trim import Trimmed
from fastfoto_linux.documents.units import MM_PER_INCH, mm_to_px
from fastfoto_linux.imaging import RGB_NDIM

STAPLE_MAX_MM = 1.8  # a staple hole's whole shape is no longer than this (real: 1.35 at most)
PUNCH_MIN_MM = 4.0  # a punched hole is a round disc at least this long (punches are about 6 mm)
HOLE_MAX_MM = 8.0  # ... and no longer than this; nothing longer is a hole
PUNCH_ASPECT_MIN = 0.8  # a punched hole's box is nearly square: the short side over the long
PUNCH_FILL_MIN = 0.6  # ... and the hole fills this much of its box (a disc fills 0.78, a ring less)
EDGE_ZONE_MM = 25.0  # staples, clips and punches sit this near an edge of the page, or nearer
SHIFT_MM = 2.0  # the mirrored spot is searched this far to each side
MATCH_IOU = 0.5  # the two shapes overlap by at least this share of their union
SIZE_RATIO = 1.5  # each side of the other shape's box is within this factor of the mark's
HOLE_TONE = 160  # a pixel darker than this (darkest colour channel) is part of a dark shape
HOLE_DARKEST_MIN = 60  # a hole's darkest pixel is no darker than this, on both sides (print: 0-12)
HOLE_TONE_MATCH = 30  # the darkest pixels of the two sides are this near (real holes: 15 apart)
HOLE_TINT = 12  # a hole's mean blue less red is this near 0 (real holes: 4)
OFFSET_SPREAD_MM = (
    0.5  # the holes of a page lie this near one offset from their mirrors (real: 0.1)
)

HOLES_TO_COMPARE = 2  # a page with fewer holes than this has no registration to disagree about

_Key = tuple[int, int]  # where a shape lies on the other side: its box's top left corner
_Offset = tuple[float, float]  # where a shape lies from its mirrored spot, in pixels (x, y)


@dataclass(frozen=True)
class _Tone:
    """How dark a dark shape is at its darkest, and how blue (blue less red, on average)."""

    darkest: int
    tint: float

    @property
    def is_hole_grey(self) -> bool:
        return self.darkest >= HOLE_DARKEST_MIN and abs(self.tint) <= HOLE_TINT

    def matches(self, other: "_Tone") -> bool:
        return abs(self.darkest - other.darkest) <= HOLE_TONE_MATCH


@dataclass(frozen=True)
class _Shape:
    """The dark pixels of a mark, cropped to their box, where the box's top left corner lies in
    the pixels of its page, and how dark they are."""

    mask: np.ndarray
    x: int
    y: int
    tone: _Tone

    @property
    def sides(self) -> tuple[int, int]:
        """The short and the long side of the box in pixels."""
        short, long = sorted(self.mask.shape)
        return short, long


def _dark(pixels: np.ndarray) -> np.ndarray:
    grey = pixels.min(axis=2) if pixels.ndim == RGB_NDIM else pixels
    return grey < HOLE_TONE


def _tone_of(pixels: np.ndarray, where: np.ndarray) -> _Tone:
    """The darkest pixel (darkest colour channel) and the mean blue less red of the ``where``
    part of ``pixels``, which holds at least one pixel."""
    chosen = pixels[where]
    if pixels.ndim == RGB_NDIM:
        return _Tone(int(chosen.min()), float(chosen[:, 2].mean() - chosen[:, 0].mean()))
    return _Tone(int(chosen.min()), 0.0)


def _mm(pixels: int, dpi: int) -> float:
    return pixels * MM_PER_INCH / dpi


def _hole_sized(box: tuple[int, int], dark: int, dpi: int) -> bool:
    """Whether a dark shape with a ``box`` (height, width) of ``dark`` pixels is a hole's size and
    shape: a staple hole (its long side at most ``STAPLE_MAX_MM``, whatever its shape) or a
    punched one (a round, filled disc, ``PUNCH_MIN_MM`` to ``HOLE_MAX_MM`` long). Anything in
    between is not a hole, nor is a long, thin or ring-shaped mark: print is neither small enough
    nor a disc."""
    short, long = sorted(box)
    if long <= mm_to_px(STAPLE_MAX_MM, dpi):
        return True
    if not mm_to_px(PUNCH_MIN_MM, dpi) <= long <= mm_to_px(HOLE_MAX_MM, dpi):
        return False
    return short >= PUNCH_ASPECT_MIN * long and dark >= PUNCH_FILL_MIN * short * long


def _could_be_hole(mark: Mark, page: LoadedPage) -> bool:
    """Whether a mark is small enough, and near enough to an edge, to be a hole."""
    height, width = page.pixels.shape[:2]
    longer = max(mark.x1 - mark.x0, mark.y1 - mark.y0)
    edge = min(mark.x0, mark.y0, width - mark.x1, height - mark.y1)
    return _mm(longer, page.dpi) <= HOLE_MAX_MM and _mm(edge, page.dpi) <= EDGE_ZONE_MM


def _shape_of(page: LoadedPage, mark: Mark) -> _Shape | None:
    """The whole dark shape of a mark: the dark connected pixels (``HOLE_TONE``) that meet its
    box, cropped to their own bounding box. The box is only where the shape is found: the blank
    margin clips it, and a hole that straddles the margin goes on beyond it. None when the box
    holds nothing dark (a mark that is only pale cannot be the dark backing seen through a hole),
    when the shape is not a hole's size and shape (``_hole_sized``: a small mark joined to a long
    dark line is content), or when it is not hole grey (``_Tone``: black print and ink, and
    colours, are not the backing).

    Only the window ``HOLE_MAX_MM`` round the box is looked at: a shape that reaches its edge is
    longer than that, whatever lies beyond."""
    height, width = page.pixels.shape[:2]
    reach = mm_to_px(HOLE_MAX_MM, page.dpi) + 1
    left, top = max(mark.x0 - reach, 0), max(mark.y0 - reach, 0)
    right, bottom = min(mark.x1 + reach, width), min(mark.y1 + reach, height)
    region = page.pixels[top:bottom, left:right]
    _, labels = cv2.connectedComponents(_dark(region).astype(np.uint8), connectivity=8)
    inside = labels[mark.y0 - top : mark.y1 - top, mark.x0 - left : mark.x1 - left]
    wanted = np.unique(inside[inside > 0])
    if len(wanted) == 0:
        return None
    joined = np.isin(labels, wanted)
    rows, columns = np.nonzero(joined)
    first_row, first_column = int(rows.min()), int(columns.min())
    whole = joined[first_row : int(rows.max()) + 1, first_column : int(columns.max()) + 1]
    tone = _tone_of(region, joined)
    if not _hole_sized(whole.shape, int(whole.sum()), page.dpi) or not tone.is_hole_grey:
        return None
    return _Shape(whole, left + first_column, top + first_row, tone)


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


def _window(pixels: np.ndarray, left: int, top: int, size: tuple[int, int]) -> np.ndarray:
    """The pixels of the ``size`` (height, width) area at (``left``, ``top``) of a page; where the
    area leaves the page there is paper (white)."""
    height, width = size
    window = np.full((height, width, *pixels.shape[2:]), WHITE, dtype=pixels.dtype)
    first_x, first_y = max(left, 0), max(top, 0)
    last_x = min(left + width, pixels.shape[1])
    last_y = min(top + height, pixels.shape[0])
    if last_x > first_x and last_y > first_y:
        window[first_y - top : last_y - top, first_x - left : last_x - left] = pixels[
            first_y:last_y, first_x:last_x
        ]
    return window


def _same_size(first: tuple[int, int], second: tuple[int, int]) -> bool:
    return all(max(a, b) <= SIZE_RATIO * min(a, b) for a, b in zip(first, second, strict=True))


def _could_explain(shape: _Shape, box: tuple[int, int], dark: int, dpi: int) -> bool:
    """Whether a dark shape on the other side, with a ``box`` (height, width) of ``dark`` pixels,
    is a hole's size and the size of ``shape`` (the hole it would be the other end of)."""
    return _hole_sized(box, dark, dpi) and _same_size(shape.sides, tuple(sorted(box)))


def _overlap(template: np.ndarray, shape: np.ndarray, pad: int, reach: int) -> float:
    """The best intersection over union of ``template`` with ``shape`` over every shift of up to
    ``reach`` pixels from the spot ``pad`` pixels in from the corner of the canvas of ``shape``."""
    common = cv2.matchTemplate(shape.astype(np.float32), template.astype(np.float32), cv2.TM_CCORR)
    near = np.rint(common[pad - reach : pad + reach + 1, pad - reach : pad + reach + 1])
    union = int(template.sum()) + int(shape.sum()) - near
    return float((near / union).max())


@dataclass(frozen=True)
class _Match:
    """A shape on the partner's side that explains a mark: where its box lies, and its offset."""

    key: _Key
    offset: _Offset


def _counterpart(shape: _Shape, side: Trimmed, partner: Trimmed, taken: set[_Key]) -> _Match | None:
    """The dark shape on the partner's side that matches ``shape`` at the mirrored spot (the same
    size, the same grey and overlapping it) and has not explained another mark yet, the best
    overlap first; None when there is none."""
    dpi = side.page.dpi
    reach = mm_to_px(SHIFT_MM, dpi)
    pad = reach + mm_to_px(HOLE_MAX_MM * SIZE_RATIO, dpi)
    height, width = shape.mask.shape
    x, y = _mirrored(shape, side, partner)
    window = _window(partner.page.pixels, x - pad, y - pad, (height + 2 * pad, width + 2 * pad))
    template = shape.mask[:, ::-1]
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        _dark(window).astype(np.uint8), connectivity=8
    )
    best: tuple[float, _Match] | None = None
    for label in range(1, count):
        left, top, wide, tall, dark = stats[label].tolist()
        key = (left + x - pad, top + y - pad)
        touches_edge = left == 0 or top == 0 or left + wide == window.shape[1]
        touches_edge = touches_edge or top + tall == window.shape[0]
        if touches_edge or key in taken or not _could_explain(shape, (tall, wide), dark, dpi):
            continue
        tone = _tone_of(window, labels == label)
        if not (tone.is_hole_grey and shape.tone.matches(tone)):
            continue
        overlap = _overlap(template, labels == label, pad, reach)
        if overlap >= MATCH_IOU and (best is None or overlap > best[0]):
            offset = (left + wide / 2 - pad - width / 2, top + tall / 2 - pad - height / 2)
            best = (overlap, _Match(key, offset))
    return None if best is None else best[1]


def _share_one_registration(offsets: Sequence[_Offset], dpi: int) -> bool:
    """Whether the offsets of a page's holes agree within ``OFFSET_SPREAD_MM`` on each axis (a
    page with fewer than two has nothing to disagree with)."""
    if len(offsets) < HOLES_TO_COMPARE:
        return True
    spread = np.ptp(np.array(offsets), axis=0)
    return bool((spread <= mm_to_px(OFFSET_SPREAD_MM, dpi)).all())


@dataclass(frozen=True)
class HoleReport:
    """How the marks of a page fare as holes: how many could be one (``candidates``: a hole's
    size, shape, grey and place), how many of those the other side shows too (``matched``), and
    whether every mark is such a hole (``all_matched``)."""

    matched: int
    candidates: int
    all_matched: bool


def hole_report(marks: Sequence[Mark], side: Trimmed, partner: Trimmed) -> HoleReport:
    """Weigh every mark of ``side`` against ``partner``, the other side of the same sheet (see the
    module's text): ``all_matched`` is whether every mark is a hole through the paper that
    ``partner`` shows too. No marks is not a hole: the caller has already called that page
    blank."""
    page = side.page
    comparable = _comparable(side, partner)
    taken: set[_Key] = set()
    offsets: list[_Offset] = []
    candidates = 0
    for mark in marks:
        shape = _shape_of(page, mark) if _could_be_hole(mark, page) else None
        if shape is None:
            continue
        candidates += 1
        found = _counterpart(shape, side, partner, taken) if comparable else None
        if found is not None:
            taken.add(found.key)
            offsets.append(found.offset)
    matched = len(offsets)
    every = bool(marks) and comparable and matched == len(marks)
    return HoleReport(matched, candidates, every and _share_one_registration(offsets, page.dpi))


def all_are_holes(marks: Sequence[Mark], side: Trimmed, partner: Trimmed) -> bool:
    """Whether every mark of ``side`` is a hole through the paper that ``partner``, the other
    side of the same sheet, shows too (see the module's text and ``hole_report``)."""
    return hole_report(marks, side, partner).all_matched
