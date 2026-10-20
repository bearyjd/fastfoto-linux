"""Exact, lossless crop and clockwise quarter-turn of RGB pixels."""

import numpy as np

from fastfoto_linux.photo_edits.model import PhotoGeometry, PhotoSource


def apply_geometry(pixels: np.ndarray, geometry: PhotoGeometry) -> np.ndarray:
    """Crop in source space, then turn clockwise; always a new C-contiguous array."""
    height, width = pixels.shape[:2]
    left, top, right, bottom = geometry.crop or (0, 0, width, height)
    turned = np.rot90(pixels[top:bottom, left:right], k=-geometry.quarter_turns)
    return np.array(turned, dtype=np.uint8, order="C", copy=True)


def output_size(source: PhotoSource, geometry: PhotoGeometry) -> tuple[int, int]:
    """The (width, height) a recipe with this geometry produces."""
    left, top, right, bottom = geometry.crop or (0, 0, source.width, source.height)
    width, height = right - left, bottom - top
    return (height, width) if geometry.quarter_turns % 2 else (width, height)
