"""Find the marks on a page: letter-sized spots that clearly differ from the paper.

Dust, paper texture and faint show-through from the other side are not marks; anything a reader
could take for writing is, however big (a signature is one large mark). Every length is in
millimetres and turned into pixels with the page's resolution.
"""

from dataclasses import dataclass

import cv2
import numpy as np

from fastfoto_linux.documents.loader import LoadedPage
from fastfoto_linux.documents.units import MM_PER_INCH, mm_to_px
from fastfoto_linux.imaging import RGB_NDIM

WORK_DPI = 150  # pages sharper than this are shrunk (keeping the darkest pixel) before analysis
BACKGROUND_KERNEL_MM = 8.0  # dark features thinner than this are ink, not paper
LOCAL_CONTRAST = 45  # grey levels darker than the paper around it
PAGE_CONTRAST = 80  # grey levels darker than the page's usual paper tone (big flat areas)
VERY_DARK = 96  # a pixel this dark is a mark whatever is around it
MARK_MIN_MM = 1.0  # the longer side of a mark is at least this: a letter, not a speck
MARK_MIN_AREA_MM2 = 0.3
_TONES = 256
_HISTOGRAM_SMOOTHING = 5


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


def _shrink(grey: np.ndarray, factor: int) -> np.ndarray:
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


def find_marks(page: LoadedPage, *, margin_mm: float = 0.0) -> tuple[Mark, ...]:
    """The marks on ``page`` that lie inside a margin of ``margin_mm`` on every side.

    A mark is a connected spot that is dark against the local paper tone (or very dark outright)
    and at least a letter's size; dust, paper texture and faint show-through are not marks.
    """
    factor = max(1, int(page.dpi // WORK_DPI))
    work_dpi = page.dpi / factor
    grey = _shrink(_darkest_channel(page.pixels), factor)
    margin = mm_to_px(margin_mm, work_dpi) if margin_mm > 0 else 0
    mask = _dark_mask(grey, work_dpi)[
        margin : grey.shape[0] - margin, margin : grey.shape[1] - margin
    ]
    if mask.size == 0:
        return ()
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    side = mm_to_px(MARK_MIN_MM, work_dpi)
    area = max(1, int(np.ceil(MARK_MIN_AREA_MM2 * (work_dpi / MM_PER_INCH) ** 2)))
    boxes = stats[1:count]  # row 0 is the background
    wanted = (np.maximum(boxes[:, 2], boxes[:, 3]) >= side) & (boxes[:, 4] >= area)
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
