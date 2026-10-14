"""Shared assertions and frames for the crop tests."""

import numpy as np

from fastfoto_linux.pipeline.crop import Box
from fastfoto_linux.pipeline.geometry import mm_to_px
from tests.synth import BACKGROUND_RGB

TOLERANCE_MM = 1.0
SIDES = ("front", "back")
CROP_LOGGER = "fastfoto_linux.pipeline.crop"


def assert_box_matches(
    found: Box, expected: Box, dpi: int, tolerance_mm: float = TOLERANCE_MM
) -> None:
    """Every edge within ``tolerance_mm`` (numbers only in the failure message)."""
    fx, fy, fw, fh = found.mm(dpi)
    ex, ey, ew, eh = expected.mm(dpi)
    edges = {
        "left": (fx, ex),
        "top": (fy, ey),
        "right": (fx + fw, ex + ew),
        "bottom": (fy + fh, ey + eh),
    }
    off = {name: round(f - e, 2) for name, (f, e) in edges.items() if abs(f - e) > tolerance_mm}
    assert not off, f"edges off by more than {tolerance_mm} mm at {dpi} dpi: {off}"


def background_only(dpi: int, size_mm: tuple[float, float] = (120, 150)) -> np.ndarray:
    """A frame of nothing but noisy scanner background."""
    rng = np.random.default_rng(1)
    shape = (mm_to_px(size_mm[1], dpi), mm_to_px(size_mm[0], dpi), 3)
    noise = rng.normal(0, 3, size=shape)
    return np.clip(np.asarray(BACKGROUND_RGB) + noise, 0, 255).astype(np.uint8)
