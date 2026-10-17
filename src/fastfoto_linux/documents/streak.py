"""A thin light streak down the scanner's backing band is the scanner's, not content."""

import numpy as np

STREAK_MAX_MM = 0.3
STREAK_LIGHTER = 4.0
STREAK_SHARE = 0.9
STREAK_MIN_MM = 3.0


def streak_pixels(smooth: np.ndarray, dpi: int) -> np.ndarray:
    """The pixels of ``smooth`` (a blurred colour strip of a band cut) that are a light streak."""
    raise NotImplementedError("streak_pixels")
