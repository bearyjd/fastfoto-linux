"""Find the marks on a page: letter-sized spots that clearly differ from the paper.

Dust, paper texture and faint show-through from the other side are not marks; anything a reader
could take for writing is, however big (a signature is one large mark). Every length is in
millimetres and turned into pixels with the page's resolution.

The blank rule also leaves out a fold crease: a faint line. A line is a mark that is straight
(``STRAIGHT_SHARE`` of its pixels within ``STRAIGHT_TOLERANCE_MM`` of its principal axis, so a
slanted one counts), thin (``STROKE_MAX_MM`` wide on average) and at least ``ELONGATION_MIN``
times longer than wide; it is faint when no part of it is darker than ``FAINT_DARKEST`` and a mark
by itself. Writing is never straight for long, however thin the pen or faint the pencil. The
letter folded in thirds that was scanned on both sides has creases on its blank back. A dark speck
on a crease is dust and does not count; dark ink touching one (a letter, a stem, a "7") does.
Limits: a faint straight single stroke (an "l", an "I", a "-", a "!", a ruled line) is a line too
and may be ignored, as may the stems of a faint "i" or "ii"; creases that cross are one big mark
and keep the page.
"""

from dataclasses import dataclass

import cv2
import numpy as np

from fastfoto_linux.documents.loader import LoadedPage, require_size
from fastfoto_linux.documents.units import MM_PER_INCH, mm_to_px
from fastfoto_linux.imaging import RGB_NDIM

WORK_DPI = 150  # pages sharper than this are shrunk (keeping the darkest pixel) before analysis
BACKGROUND_KERNEL_MM = 8.0  # dark features thinner than this are ink, not paper
LOCAL_CONTRAST = 45  # grey levels darker than the paper around it
PAGE_CONTRAST = 80  # grey levels darker than the page's usual paper tone (big flat areas)
VERY_DARK = 96  # a pixel this dark is a mark whatever is around it
MARK_MIN_MM = 1.0  # the longer side of a mark is at least this: a letter, not a speck
MARK_MIN_AREA_MM2 = 0.3
# A fold crease is a straight, thin, faint line, and a blank back must not be kept for it. Real
# creases: straight along the paper's axes, 0.17-0.51 mm thick, 2-23 mm long, darkest pixel
# 152-204; a deskew artefact: straight, 2.8 degrees off vertical, 153 mm long, darkest 176.
# Real text: darkest pixel 0-120.
STROKE_MAX_MM = 0.8  # a line is this wide or thinner on average: its area over its length
STRAIGHT_TOLERANCE_MM = 0.4  # a pixel this near the principal axis is on the line (half of 0.8)
STRAIGHT_SHARE = 0.9  # a line has at least this share of its pixels on the axis
ELONGATION_MIN = 2.5  # a line is this many times longer than wide (the squattest crease: 3.9;
# a pencil comma or a dot: under 2)
FAINT_DARKEST = 140  # a part of a line darker than this may be a mark by itself (creases: 152+)
SPECK_MIN_MM = 0.5  # a dark part this wide is a speck on the line; thinner is the line's grain
INNER_MM = 0.8  # a mark nearer a line's axis than this is on the line itself (pieces of a crease)
OUTER_MM = 4.0  # a mark this near, alongside a line, is a neighbour: writing has them, a crease not
DUST_HALO_MM = 0.3  # the blur round a dark speck, taken off a line before it is judged
_TONES = 256
_HISTOGRAM_SMOOTHING = 5


@dataclass(frozen=True)
class _Scale:
    """How a page was shrunk for analysis, and the smallest area (in shrunk pixels) of a mark."""

    factor: int
    dpi: float  # the page's, not the shrunk one's
    area: int


@dataclass(frozen=True)
class Mark:
    """Bounding box of one mark in page pixels (end exclusive)."""

    x0: int
    y0: int
    x1: int
    y1: int


def _darkest_channel(pixels: np.ndarray) -> np.ndarray:
    """The darkest of the colour channels, so coloured ink and highlighter count as ink."""
    return pixels.min(axis=2) if pixels.ndim == RGB_NDIM else pixels


def shrink_keeping_darkest(grey: np.ndarray, factor: int) -> np.ndarray:
    """``grey`` reduced ``factor`` times keeping the darkest pixel of each block: thin pencil
    strokes keep their full contrast."""
    if factor == 1:
        return grey
    height, width = (size // factor * factor for size in grey.shape)
    blocks = grey[:height, :width].reshape(height // factor, factor, width // factor, factor)
    return blocks.min(axis=(1, 3))


def _paper_tone(grey: np.ndarray) -> int:
    histogram = np.bincount(grey.ravel(), minlength=_TONES).astype(np.float64)
    smooth = np.convolve(histogram, np.ones(_HISTOGRAM_SMOOTHING), mode="same")
    return int(smooth.argmax())


def _dark_mask(grey: np.ndarray, work_dpi: float) -> np.ndarray:
    size = mm_to_px(BACKGROUND_KERNEL_MM, work_dpi) | 1
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (size, size))
    background = cv2.morphologyEx(grey, cv2.MORPH_CLOSE, kernel)
    local = cv2.subtract(background, grey) >= LOCAL_CONTRAST
    page = (_paper_tone(grey) - grey.astype(np.int16)) >= PAGE_CONTRAST
    return (local | page | (grey < VERY_DARK)).astype(np.uint8)


def _source_sides(boxes: np.ndarray, factor: int) -> np.ndarray:
    """The short and the long side of each box in source pixels, less the ``factor - 1`` pixels
    that keeping the darkest pixel of a block adds (see ``find_marks``). Shape (n, 2)."""
    return np.sort(boxes[:, 2:4], axis=1) * factor - (factor - 1)


def _is_mark_sized(boxes: np.ndarray, scale: _Scale) -> np.ndarray:
    """Which components are at least a letter long (in source pixels) and cover the area."""
    length = _source_sides(boxes, scale.factor)[:, 1]
    return (length >= mm_to_px(MARK_MIN_MM, scale.dpi)) & (boxes[:, 4] >= scale.area)


def _axes(ids: np.ndarray, xs: np.ndarray, ys: np.ndarray, size: int) -> np.ndarray:
    """Centre and direction (cos, sin) of the principal axis of each group of points. Shape (4,
    size); a group with no point gets zeros."""
    area = np.maximum(np.bincount(ids, minlength=size), 1)
    cx, cy = np.bincount(ids, xs, size) / area, np.bincount(ids, ys, size) / area
    dx, dy = xs - cx[ids], ys - cy[ids]
    sxx, syy = np.bincount(ids, dx * dx, size), np.bincount(ids, dy * dy, size)
    angle = 0.5 * np.arctan2(2 * np.bincount(ids, dx * dy, size), sxx - syy)
    return np.stack([cx, cy, np.cos(angle), np.sin(angle)])


def _along_across(
    ids: np.ndarray, xs: np.ndarray, ys: np.ndarray, axes: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """How far each point is along its group's axis and how far off it."""
    cx, cy, cos, sin = axes[:, ids]
    dx, dy = xs - cx, ys - cy
    return dx * cos + dy * sin, dy * cos - dx * sin


def _tolerance(scale: _Scale) -> float:
    """``STRAIGHT_TOLERANCE_MM`` in working pixels, with the growth of keeping the darkest pixel
    of each block (half of it on each side of a line)."""
    return (STRAIGHT_TOLERANCE_MM * scale.dpi / MM_PER_INCH + (scale.factor - 1) / 2) / scale.factor


def _extent(labels: np.ndarray, axes: np.ndarray, size: int) -> np.ndarray:
    """How long each component of ``labels`` is along the axis of its group, in pixels."""
    ys, xs = np.nonzero(labels)
    ids = labels[ys, xs]
    along, _ = _along_across(ids, xs, ys, axes)
    low, high = np.full(size, np.inf), np.full(size, -np.inf)
    np.minimum.at(low, ids, along)
    np.maximum.at(high, ids, along)
    return np.where(np.isfinite(low), high - low + 1, 1)


def _line_like(body: np.ndarray, whole: np.ndarray, size: int, scale: _Scale) -> np.ndarray:
    """Which components (by label, ``size`` of them with 0) are straight, thin and elongated:
    lines. Writing is not straight for long; a pale highlighter band is not thin.

    ``body`` is each component less its dust, ``whole`` the component as it is. Straight:
    ``STRAIGHT_SHARE`` of the body's pixels lie within ``STRAIGHT_TOLERANCE_MM`` of its principal
    axis. Thin: the body's area over its length along the axis, in source pixels (less the growth
    of keeping the darkest pixel of each block), is at most ``STROKE_MAX_MM``. Elongated: the
    whole component is ``ELONGATION_MIN`` times longer along that axis than thick.
    """
    ys, xs = np.nonzero(body)
    ids = body[ys, xs]
    axes = _axes(ids, xs, ys, size)
    _, across = _along_across(ids, xs, ys, axes)
    area = np.bincount(ids, minlength=size)
    near = np.bincount(ids[np.abs(across) <= _tolerance(scale)], minlength=size)
    grown = scale.factor - 1
    thick = area / _extent(body, axes, size) * scale.factor - grown
    long = _extent(whole, axes, size) * scale.factor - grown
    return (
        (area > 0)
        & (near >= STRAIGHT_SHARE * area)
        & (thick <= mm_to_px(STROKE_MAX_MM, scale.dpi))
        & (long >= ELONGATION_MIN * thick)
    )


def _parents(pieces: np.ndarray, labels: np.ndarray, count: int) -> np.ndarray:
    """The component of ``labels`` that each piece (a labelled part of one) lies in."""
    parent = np.zeros(count, dtype=labels.dtype)
    inside = pieces > 0
    parent[pieces[inside]] = labels[inside]
    return parent


def _square(mm: float, work_dpi: float, *, grow: bool = False) -> np.ndarray:
    """A square structuring element ``mm`` wide, or ``mm`` each side of a pixel if ``grow``."""
    side = 2 * mm_to_px(mm, work_dpi) + 1 if grow else mm_to_px(mm, work_dpi)
    return np.ones((side, side), np.uint8)


def _dust(dark: np.ndarray, scale: _Scale) -> np.ndarray:
    """The dark specks (parts wider than a stroke, grown by their blur) of a ``dark`` mask."""
    work_dpi = scale.dpi / scale.factor
    wide = cv2.morphologyEx(dark, cv2.MORPH_OPEN, _square(SPECK_MIN_MM, work_dpi))
    return cv2.dilate(wide, _square(DUST_HALO_MM, work_dpi, grow=True)) > 0


def _strip(line: np.ndarray, scale: _Scale, *, needs_length: bool) -> np.ndarray:
    """The straight strip that the pixels of ``line`` lie along, over the whole window, as wide as
    the line itself (at most ``STRAIGHT_TOLERANCE_MM`` each side of its axis).

    Empty when ``needs_length`` and ``line`` is shorter than a mark: a stub tells nothing of the
    line's course."""
    ys, xs = np.nonzero(line)
    if len(ys) == 0:
        return np.zeros(line.shape, dtype=bool)
    zeros = np.zeros(len(ys), dtype=np.intp)
    axes = _axes(zeros, xs, ys, 1)
    along, across = _along_across(zeros, xs, ys, axes)
    span = (along.max() - along.min() + 1) * scale.factor - (scale.factor - 1)
    if needs_length and span < mm_to_px(MARK_MIN_MM, scale.dpi):
        return np.zeros(line.shape, dtype=bool)
    half = min(_tolerance(scale), np.abs(across).max() + 0.5)
    rows, columns = np.indices(line.shape)
    cx, cy, cos, sin = axes[:, 0]
    return np.abs((rows - cy) * cos - (columns - cx) * sin) <= half


def _is_ink_a_mark(
    labels: np.ndarray, dark: np.ndarray, box: np.ndarray, index: int, scale: _Scale
) -> bool:
    """Whether what is on component ``index + 1`` besides its line would be a mark on its own.

    The line is the straight strip its pixels, away from the halo of every dark part, lie along;
    the ink is what lies off it, and the dark parts. A stroke on its own has no line left to
    follow: all of it is ink.
    """
    x, y, width, height, _ = box.tolist()
    window = (slice(y, y + height), slice(x, x + width))
    mine = labels[window] == index + 1
    core = (dark[window] > 0) & mine
    halo = cv2.dilate(
        core.astype(np.uint8), _square(DUST_HALO_MM, scale.dpi / scale.factor, grow=True)
    )
    strip = _strip(mine & (halo == 0), scale, needs_length=bool(core.any()))
    _, _, stats, _ = cv2.connectedComponentsWithStats(
        (core | (mine & ~strip)).astype(np.uint8), connectivity=8
    )
    return bool(_is_mark_sized(stats[1:], scale).any())


def _faint_lines(
    labels: np.ndarray, grey: np.ndarray, boxes: np.ndarray, wanted: np.ndarray, scale: _Scale
) -> np.ndarray:
    """Which components (rows of ``boxes``) are faint lines.

    A component that holds a dark cluster (darker than ``FAINT_DARKEST``) that is a mark by
    itself is not one. The others must be lines (``_line_like``) after their dark specks are
    taken off, which are dust: a speck on a crease leaves the crease. A speck is a dark part wider
    than a stroke, grown by its blur; thinner dark parts are the grain of the line itself. A line
    is still not faint when the ink on it, the dark parts and whatever lies off its strip, would
    be a mark on its own (a hairline stem, a "7").
    """
    size = len(boxes) + 1
    dark = ((labels > 0) & (grey < FAINT_DARKEST)).astype(np.uint8)
    count, clusters, stats, _ = cv2.connectedComponentsWithStats(dark, connectivity=8)
    held = np.zeros(size, dtype=bool)
    held[_parents(clusters, labels, count)[1:][_is_mark_sized(stats[1:], scale)]] = True
    active = np.concatenate([[False], wanted]) & ~held
    whole = np.where(active[labels], labels, 0)
    lines = active & _line_like(np.where(_dust(dark, scale), 0, whole), whole, size, scale)
    for index in np.nonzero(lines)[0]:
        if _is_ink_a_mark(labels, dark, boxes[index - 1], int(index) - 1, scale):
            lines[index] = False
    return lines[1:]


def find_marks(
    page: LoadedPage,
    *,
    margin_mm: float = 0.0,
    trimmed_bottom: int = 0,
    ignore_faint_lines: bool = False,
) -> tuple[Mark, ...]:
    """The marks on ``page`` that lie inside a margin of ``margin_mm`` on every side.

    A mark is a connected spot that is dark against the local paper tone (or very dark outright)
    and at least a letter's size; dust, paper texture and faint show-through are not marks.
    ``trimmed_bottom`` rows were cut off the bottom of the scanner's frame before ``page`` was
    made; the bottom margin is the frame's, so it is that much smaller. A page under 10 mm each
    way raises UnsupportedPageError: no marks must never be mistaken for a blank page.

    With ``ignore_faint_lines`` a fold crease is not a mark either: a straight (``STRAIGHT_SHARE``
    of its pixels within ``STRAIGHT_TOLERANCE_MM`` of its axis), thin (``STROKE_MAX_MM``) and
    elongated (``ELONGATION_MIN``) stroke, with no part darker than ``FAINT_DARKEST`` that is a
    mark by itself (a dark speck on it is dust, dark ink on it is ink). Other marks are as without
    it.
    """
    require_size(page.pixels.shape[1], page.pixels.shape[0], page.dpi)
    factor = max(1, int(page.dpi // WORK_DPI))
    work_dpi = page.dpi / factor
    grey = shrink_keeping_darkest(_darkest_channel(page.pixels), factor)
    margin = mm_to_px(margin_mm, work_dpi) if margin_mm > 0 else 0
    bottom = max(0, margin - trimmed_bottom // factor)
    rows, columns = slice(margin, grey.shape[0] - bottom), slice(margin, grey.shape[1] - margin)
    mask = _dark_mask(grey, work_dpi)[rows, columns]
    if mask.size == 0:
        return ()
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    area = max(1, int(np.ceil(MARK_MIN_AREA_MM2 * (work_dpi / MM_PER_INCH) ** 2)))
    boxes = stats[1:count]  # row 0 is the background
    # Keeping the darkest pixel of each block widens a spot by factor - 1 source pixels on
    # average, so a speck would grow past the size limit at 600 dpi and not at 200: the length
    # is judged in source pixels, less that growth.
    scale = _Scale(factor, page.dpi, area)
    wanted = _is_mark_sized(boxes, scale)
    if ignore_faint_lines:
        wanted &= ~_faint_lines(labels, grey[rows, columns], boxes, wanted, scale)
    marks = [
        Mark(
            (x + margin) * factor,
            (y + margin) * factor,
            (x + width + margin) * factor,
            (y + height + margin) * factor,
        )
        for x, y, width, height, _ in boxes[wanted].tolist()
    ]
    return tuple(sorted(marks, key=lambda mark: (mark.y0, mark.x0)))
