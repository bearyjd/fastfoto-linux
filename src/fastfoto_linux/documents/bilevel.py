"""Black-and-white conversion with an adaptive threshold.

A pixel turns black in one of two ways:

* it is darker than ``DARK_LEVEL``: solid dark areas (a logo, a black bar, a reversed heading)
  are black all the way through, wherever they are;
* it is at least ``BELOW_LOCAL_MEAN`` darker than the local paper tone (the mean over a window
  of ``WINDOW_MM``) *and* than the paper beside it (the page with strokes thinner than the
  window removed, a morphological closing). The first alone follows uneven lighting; the second
  stops it from drawing a black outline round the edge of a shaded box.

Shading lighter than ``DARK_LEVEL`` is therefore background: a filled grey box comes out white,
and text inside it stays black. A one-bit page cannot hold the grey, and an outline or a solid
fill would hide or damage what is written on it.
"""

import cv2
import numpy as np

from fastfoto_linux.documents.loader import WHITE
from fastfoto_linux.documents.marks import VERY_DARK, WORK_DPI, shrink_keeping_darkest
from fastfoto_linux.documents.units import mm_to_px

WINDOW_MM = 8.0  # the local paper tone is the mean over a window about this wide
BELOW_LOCAL_MEAN = 25  # a pixel is black when it is this much darker than that mean
DARK_LEVEL = VERY_DARK  # a pixel darker than this is always black
_MIN_WINDOW = 3


def _odd(size: int) -> int:
    return max(_MIN_WINDOW, size | 1)


def _darker_than_paper_beside(grey: np.ndarray, dpi: int) -> np.ndarray:
    """True where a pixel is ``BELOW_LOCAL_MEAN`` darker than the closing of the page.

    The closing removes dark strokes thinner than the window and keeps wide dark areas, so it
    is the paper (or the shading) a stroke lies on. It is computed on a copy shrunk to about
    ``WORK_DPI``, which keeps it fast at 600 dpi.
    """
    factor = max(1, min(dpi // WORK_DPI, *grey.shape))
    small = shrink_keeping_darkest(grey, factor)
    size = _odd(mm_to_px(WINDOW_MM, dpi / factor))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (size, size))
    closed = cv2.morphologyEx(small, cv2.MORPH_CLOSE, kernel)
    paper = np.repeat(np.repeat(closed, factor, axis=0), factor, axis=1)
    missing = ((0, grey.shape[0] - paper.shape[0]), (0, grey.shape[1] - paper.shape[1]))
    return cv2.subtract(np.pad(paper, missing, mode="edge"), grey) >= BELOW_LOCAL_MEAN


def binarise(grey: np.ndarray, dpi: int) -> np.ndarray:
    """A boolean array, True where the page is white, from an ``HxW`` uint8 grey page.

    The threshold follows the local paper tone over a window of a few millimetres at ``dpi``,
    so uneven lighting does not turn paper black; see the module text for solid dark areas and
    shading. The input is not modified.
    """
    window = _odd(mm_to_px(WINDOW_MM, dpi))
    white = cv2.adaptiveThreshold(
        grey, WHITE, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, window, BELOW_LOCAL_MEAN
    )
    stroke = (white != WHITE) & _darker_than_paper_beside(grey, dpi)
    return ~((grey < DARK_LEVEL) | stroke)
