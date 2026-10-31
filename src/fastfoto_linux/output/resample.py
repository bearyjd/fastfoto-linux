"""Downscaling for the small preset: area averaging, never up, the input untouched."""

import cv2
import numpy as np


def downscale(pixels: np.ndarray, max_edge: int) -> tuple[np.ndarray, float]:
    """``pixels`` with the long edge at most ``max_edge``, and the scale used (1.0: unchanged).

    Within the limit the same array comes back. Both sides use one scale, each at least 1 pixel.
    Raises ValueError for ``max_edge`` below 1.
    """
    if max_edge < 1:
        raise ValueError(f"max_edge must be at least 1, got {max_edge}")
    height, width = pixels.shape[:2]
    if max(height, width) <= max_edge:
        return pixels, 1.0
    scale = max_edge / max(height, width)
    size = (max(1, round(width * scale)), max(1, round(height * scale)))
    return cv2.resize(pixels, size, interpolation=cv2.INTER_AREA), scale


def downscale_to_dpi(pixels: np.ndarray, dpi: int, max_dpi: int) -> tuple[np.ndarray, int]:
    """``pixels`` resampled so the resolution is at most ``max_dpi``, and the resulting dpi.

    The physical size holds. At or below the limit the same array and ``dpi`` come back.
    Raises ValueError for ``max_dpi`` below 1.
    """
    if max_dpi < 1:
        raise ValueError(f"max_dpi must be at least 1, got {max_dpi}")
    if dpi <= max_dpi:
        return pixels, dpi
    scale = max_dpi / dpi
    height, width = pixels.shape[:2]
    size = (max(1, round(width * scale)), max(1, round(height * scale)))
    return cv2.resize(pixels, size, interpolation=cv2.INTER_AREA), max_dpi
