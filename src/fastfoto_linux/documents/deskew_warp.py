"""Turn a trimmed page clockwise by a small angle in the same frame, filling with white.

The frame keeps its width and height (so the crop units and the PDF page size keep their
meaning) and the turn is about the pixel centre. The matrix comes from the fixed-point
``straighten.trig`` so it is exactly reproducible. A 1-bit page is resampled by nearest
neighbour so it still holds only 0 and 255.
"""

import cv2
import numpy as np

from fastfoto_linux.documents.deskew_tables import MAX_TENTHS
from fastfoto_linux.documents.loader import WHITE
from fastfoto_linux.documents.modes import ColourMode
from fastfoto_linux.photo_edits.straighten import TRIG_BITS, trig


def check_tenths(tenths: object) -> int:
    """``tenths`` if it is a whole number (not a bool) within +-``MAX_TENTHS``, else ValueError."""
    if type(tenths) is not int or not -MAX_TENTHS <= tenths <= MAX_TENTHS:
        raise ValueError(
            f"deskew must be a whole number of tenths from -{MAX_TENTHS} to {MAX_TENTHS}"
        )
    return tenths


def deskewed(pixels: np.ndarray, tenths: int, kind: ColourMode) -> np.ndarray:
    """``pixels`` turned clockwise by ``tenths`` tenths of a degree about the page centre, new
    pixels of the same shape; the corners are white on every channel."""
    check_tenths(tenths)
    height, width = pixels.shape[:2]
    cos, sin = (value / (1 << TRIG_BITS) for value in trig(tenths))
    cx, cy = (width - 1) / 2, (height - 1) / 2
    matrix = np.array(
        [[cos, -sin, cx - cos * cx + sin * cy], [sin, cos, cy - sin * cx - cos * cy]],
        dtype=np.float64,
    )
    flags = cv2.INTER_NEAREST if kind is ColourMode.BW else cv2.INTER_LINEAR
    return cv2.warpAffine(
        pixels,
        matrix,
        (width, height),
        flags=flags,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(WHITE, WHITE, WHITE),
    )
