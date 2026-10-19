"""Deterministic antialiased scanner-text fixtures, generated without host fonts or images."""

import cv2
import numpy as np

from fastfoto_linux.documents.loader import LoadedPage
from fastfoto_linux.documents.modes import ColourMode
from fastfoto_linux.documents.units import mm_to_px


def antialiased_page(dpi: int, kind: ColourMode, extra: str = "") -> LoadedPage:
    """High-contrast dark glyphs with neutral paper noise and optional protected content."""
    shape = (mm_to_px(90, dpi), mm_to_px(75, dpi))
    grey = np.full(shape, 245, np.uint8)
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = mm_to_px(3.0, dpi) / cv2.getTextSize("Example", font, 1.0, 1)[0][1]
    for row in range(4):
        origin = (mm_to_px(8, dpi), mm_to_px(15 + 9 * row, dpi))
        cv2.putText(grey, "Example 0123", origin, font, scale, 45, mm_to_px(0.25, dpi), cv2.LINE_AA)
    rng = np.random.default_rng(611)
    grey = np.clip(grey.astype(np.int16) + rng.integers(-2, 3, shape), 0, 255).astype(np.uint8)
    y, x = mm_to_px(65, dpi), mm_to_px(12, dpi)
    if extra == "pencil":
        grey[y : y + mm_to_px(0.18, dpi), x : x + mm_to_px(25, dpi)] = 221
    elif extra == "photo":
        side = mm_to_px(15, dpi)
        grey[y : y + side, x : x + side] = np.linspace(110, 225, side, dtype=np.uint8)
    pixels = np.repeat(grey[:, :, None], 3, axis=2) if kind is ColourMode.COLOUR else grey
    return LoadedPage(pixels, kind, dpi)
