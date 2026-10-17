"""Find the marks on a page: letter-sized spots that clearly differ from the paper.

Dust, paper texture and faint show-through from the other side are not marks; anything a reader
could take for writing is, however big (a signature is one large mark). Every length is in
millimetres and turned into pixels with the page's resolution.

The blank rule also leaves out a fold crease: a faint line. A line is a mark that is a thin
stroke (``STROKE_MAX_MM`` thick on average) and either thin (``LINE_MAX_MM``) or many times longer
than wide; it is faint when no part of it is darker than ``FAINT_DARKEST`` and a mark by itself.
The letter folded in thirds that was scanned on both sides has them on its blank back. A dark
speck on a crease is dust and does not count; a dark letter touching one does. Limits: a faint
thin single stroke (an "l", an "I", a "-", a "!") and a faint flat signature wave are lines too and
may be ignored; creases that cross are one big mark and keep the page.
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
# A fold crease is a thin, faint line, and a blank back must not be kept for it. Real creases:
# 0.17-0.51 mm thick, darkest pixel 152-204. Real text: darkest pixel 0-120.
LINE_MAX_MM = 0.6  # a mark this thin or thinner is line-like (the thickest crease: 0.51)
LINE_ASPECT = 8  # a mark this many times longer than wide is line-like (a deskew artefact: 20)
STROKE_MAX_MM = 0.8  # ... but only a thin stroke: its area over its long side, at most this
FAINT_DARKEST = 140  # a part of a line darker than this may be a mark by itself (creases: 152+)
SPECK_MIN_MM = 0.5  # a dark part this wide is a speck on the line; thinner is the line's grain
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


def _line_like(boxes: np.ndarray, scale: _Scale) -> np.ndarray:
    """Which components are a thin stroke that is either thin or many times longer than wide.

    The mean thickness is the component's area over its long side (in source pixels, less the
    growth of keeping the darkest pixel of each block): faint writing and a pale highlighter band
    are not thin strokes however long they are.
    """
    factor = scale.factor
    short, long = _source_sides(boxes, factor).T
    mean = boxes[:, 4] / np.maximum(boxes[:, 2:4].max(axis=1), 1) * factor - (factor - 1)
    elongated = (short <= mm_to_px(LINE_MAX_MM, scale.dpi)) | (long >= LINE_ASPECT * short)
    return elongated & (mean <= mm_to_px(STROKE_MAX_MM, scale.dpi))


def _parents(pieces: np.ndarray, labels: np.ndarray, count: int) -> np.ndarray:
    """The component of ``labels`` that each piece (a labelled part of one) lies in."""
    parent = np.zeros(count, dtype=labels.dtype)
    inside = pieces > 0
    parent[pieces[inside]] = labels[inside]
    return parent


def _body_box(labels: np.ndarray, specks: np.ndarray, box: np.ndarray, index: int) -> np.ndarray:
    """The box (x, y, width, height, area) of component ``index + 1`` less the ``specks``; a row
    of zeros when nothing is left."""
    x, y, width, height, _ = box.tolist()
    window = (slice(y, y + height), slice(x, x + width))
    rows, columns = np.nonzero((labels[window] == index + 1) & ~specks[window])
    if rows.size == 0:
        return np.zeros_like(box)
    x0, y0 = x + columns.min(), y + rows.min()
    return np.array([x0, y0, x + columns.max() + 1 - x0, y + rows.max() + 1 - y0, rows.size])


def _faint_lines(
    labels: np.ndarray, grey: np.ndarray, boxes: np.ndarray, wanted: np.ndarray, scale: _Scale
) -> np.ndarray:
    """Which components (rows of ``boxes``) are faint lines.

    A component that holds a dark cluster (darker than ``FAINT_DARKEST``) that is a mark by
    itself is not one. The others are judged without their dark specks, which are dust: a speck
    on a crease leaves the crease. A speck is a dark part wider than a stroke, grown by its blur;
    thinner dark parts are the grain of the line itself. A component with no dark pixel is judged
    as it is.
    """
    dark = ((labels > 0) & (grey < FAINT_DARKEST)).astype(np.uint8)
    count, clusters, stats, _ = cv2.connectedComponentsWithStats(dark, connectivity=8)
    held = np.zeros(len(boxes) + 1, dtype=bool)
    held[_parents(clusters, labels, count)[1:][_is_mark_sized(stats[1:], scale)]] = True
    specky = wanted & ~held[1:] & (np.bincount(labels[dark > 0], minlength=len(held))[1:] > 0)
    shown = boxes.copy()
    if specky.any():
        work_dpi = scale.dpi / scale.factor
        wide = mm_to_px(SPECK_MIN_MM, work_dpi)
        halo = 2 * mm_to_px(DUST_HALO_MM, work_dpi) + 1
        specks = cv2.dilate(
            cv2.morphologyEx(dark, cv2.MORPH_OPEN, np.ones((wide, wide), np.uint8)),
            cv2.getStructuringElement(cv2.MORPH_RECT, (halo, halo)),
        )
        for index in np.nonzero(specky)[0]:
            shown[index] = _body_box(labels, specks > 0, boxes[index], int(index))
    left = shown[:, 4] > 0
    return left & ~held[1:] & _line_like(shown, scale)


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

    With ``ignore_faint_lines`` a fold crease is not a mark either: a thin stroke (``STROKE_MAX_MM``
    thick on average) whose short side is at most ``LINE_MAX_MM`` or whose long side is
    ``LINE_ASPECT`` times its short side, with no part darker than ``FAINT_DARKEST`` that is a mark
    by itself (a dark speck on it is dust, a dark letter on it is a letter). Other marks are as
    without it.
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
