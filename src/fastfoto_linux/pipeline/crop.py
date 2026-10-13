"""Find and cut out the photo rectangle in a raw scanimage ADF frame."""

from dataclasses import dataclass

import numpy as np


class NoPhotoFoundError(ValueError):
    """The frame contains no photo-sized region that differs from the scanner background."""


@dataclass(frozen=True)
class Box:
    """Axis-aligned rectangle in pixels: top-left corner ``(x, y)`` and size ``(w, h)``."""

    x: int
    y: int
    w: int
    h: int

    def mm(self, dpi: float) -> tuple[float, float, float, float]:
        """Return ``(x, y, w, h)`` in millimetres at the given resolution."""
        raise NotImplementedError


def find_photo_box(frame: np.ndarray, dpi: float) -> Box:
    """Locate the photo in a raw RGB frame and return its bounding box in frame pixels."""
    raise NotImplementedError


def crop(frame: np.ndarray, box: Box) -> np.ndarray:
    """Return a copy of ``frame`` restricted to ``box``."""
    raise NotImplementedError
