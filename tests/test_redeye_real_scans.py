"""Red-eye removal on the user's real, private fronts. Asserts structure only - never image data."""

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from fastfoto_linux.enhance.faces import FaceDetector
from fastfoto_linux.enhance.orient import apply_rotation
from fastfoto_linux.enhance.redeye import detect_faces_full_res, find_red_eyes, remove_red_eye

DPI = 600
# page -> (photo box x, y, w, h at 600 dpi, clockwise rotation that makes the front upright).
# Same hand-measured boxes as test_orient_real_scans.py: the crop stage is not a dependency here.
FRONTS = {
    2: ((352, 0, 4256, 3032), 270),
    4: ((384, 0, 3896, 2432), 0),
    6: ((368, 0, 4272, 3016), 0),
    8: ((384, 0, 4256, 3016), 0),
}


def _load_upright_front(scans_dir: Path, page: int) -> np.ndarray:
    (x, y, w, h), rotation = FRONTS[page]
    with Image.open(scans_dir / f"photo-{page:03d}.png") as image:
        front = np.array(image.convert("RGB"))[y : y + h, x : x + w]
    return apply_rotation(front, rotation)


@pytest.fixture(scope="module")
def detector() -> FaceDetector:
    return FaceDetector()


@pytest.mark.real_scans
@pytest.mark.parametrize("page", sorted(FRONTS))
def test_real_front_changes_nothing_outside_the_eye_rois(
    real_scans_dir: Path, detector: FaceDetector, page: int
) -> None:
    front = _load_upright_front(real_scans_dir, page)
    original = front.copy()
    fixes = find_red_eyes(front, detect_faces_full_res(front, detector))
    result = remove_red_eye(front, DPI, detector)
    inside = np.zeros(front.shape[:2], dtype=bool)
    for fix in fixes:
        x0, y0, x1, y1 = fix.roi
        inside[y0:y1, x0:x1] = True
    changed = np.any(result != front, axis=2)
    assert np.array_equal(front, original), f"page {page}: input was modified"
    assert result.shape == front.shape, f"page {page}: shape changed"
    assert result.dtype == front.dtype, f"page {page}: dtype changed"
    assert int(changed[~inside].sum()) == 0, f"page {page}: pixels changed outside the eye ROIs"
