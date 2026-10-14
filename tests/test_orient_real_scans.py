"""Orientation of the user's real, private fronts. Asserts decisions only - never image data."""

import time
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from fastfoto_linux.enhance.faces import FaceDetector
from fastfoto_linux.enhance.orient import decide_orientation

DPI = 600
MAX_SECONDS_PER_FRONT = 1.5
# page -> (photo box x, y, w, h at 600 dpi, clockwise rotation that makes the front upright).
# Measured by hand because the crop stage is not a dependency of this module.
FRONTS = {
    2: ((352, 0, 4256, 3032), 270),
    4: ((384, 0, 3896, 2432), 0),
    6: ((368, 0, 4272, 3016), 0),
    8: ((384, 0, 4256, 3016), 0),
}


def _load_front(scans_dir: Path, page: int) -> np.ndarray:
    x, y, w, h = FRONTS[page][0]
    with Image.open(scans_dir / f"photo-{page:03d}.png") as image:
        return np.array(image.convert("RGB"))[y : y + h, x : x + w]


@pytest.fixture(scope="module")
def detector() -> FaceDetector:
    return FaceDetector()


@pytest.mark.real_scans
@pytest.mark.parametrize("page", sorted(FRONTS))
def test_real_front_orientation_decision(
    real_scans_dir: Path, detector: FaceDetector, page: int
) -> None:
    front = _load_front(real_scans_dir, page)
    started = time.perf_counter()
    decision = decide_orientation(front, DPI, detector)
    elapsed = time.perf_counter() - started
    assert decision.rotation == FRONTS[page][1], f"page {page}"
    assert elapsed < MAX_SECONDS_PER_FRONT, f"page {page}: {elapsed:.2f}s"
