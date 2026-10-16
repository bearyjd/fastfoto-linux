"""Black-and-white conversion with an adaptive threshold."""

import cv2
import numpy as np

from fastfoto_linux.documents.units import mm_to_px

WINDOW_MM = 8.0  # the local paper tone is the mean over a window about this wide
BELOW_LOCAL_MEAN = 25  # a pixel is black when it is this much darker than that mean
_MIN_WINDOW = 3
_WHITE = 255


def _odd(size: int) -> int:
    return max(_MIN_WINDOW, size | 1)


def binarise(grey: np.ndarray, dpi: int) -> np.ndarray:
    """A boolean array, True where the page is white, from an ``HxW`` uint8 grey page.

    The threshold follows the local paper tone over a window of a few millimetres at ``dpi``,
    so uneven lighting does not turn paper black. The input is not modified.
    """
    window = _odd(mm_to_px(WINDOW_MM, dpi))
    white = cv2.adaptiveThreshold(
        grey, _WHITE, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, window, BELOW_LOCAL_MEAN
    )
    return white == _WHITE
