"""How a found pupil is repainted: a neutral dark pupil, a soft edge, no halo around it."""

import numpy as np
import pytest

from fastfoto_linux.enhance.redeye import EyeFix, apply_fixes

SIZE = 61
CENTRE = SIZE // 2
PUPIL_RADIUS = 6
CORE_RADIUS = 3
SKIN = (200, 150, 130)
# pupil colour -> highest luminance its corrected core may have (about half of blue-green, <= 40)
PUPILS = {
    "saturated red": ((230, 20, 20), 12),
    "faded red": ((200, 90, 80), 45),
    "dull red": ((150, 70, 60), 36),
    "orange red": ((250, 150, 140), 45),
}
MAX_CHANNEL_SPREAD = 3
HALO_NEAR_PX = 1.5
HALO_FAR_PX = 3.5
UNTOUCHED_BEYOND_PX = 5
MIN_RING_KEEP = 0.95
MAX_FRINGE_KEEP = 0.8
MAX_EDGE_STEP = 0.6
LUMA = np.array([0.299, 0.587, 0.114])


def _scene(pupil: tuple[int, int, int]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Skin with a red pupil: the image, the distance of every pixel from the pupil centre."""
    rows, cols = np.mgrid[:SIZE, :SIZE]
    distance = np.hypot(cols - CENTRE, rows - CENTRE)
    img = np.empty((SIZE, SIZE, 3), dtype=np.uint8)
    img[:] = SKIN
    img[distance <= PUPIL_RADIUS] = pupil
    mask = distance <= PUPIL_RADIUS
    mask.setflags(write=False)
    return img, mask, distance


def _corrected(pupil: tuple[int, int, int]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    img, mask, distance = _scene(pupil)
    fix = EyeFix(roi=(0, 0, SIZE, SIZE), mask=mask, center=(CENTRE, CENTRE))
    return img, apply_fixes(img, (fix,)), distance


@pytest.mark.parametrize(("pupil", "darkest"), PUPILS.values(), ids=PUPILS.keys())
def test_corrected_pupil_is_neutral_and_dark(pupil: tuple[int, int, int], darkest: float) -> None:
    _, result, distance = _corrected(pupil)
    core = result[distance <= CORE_RADIUS].astype(int)
    assert (core.max(axis=1) - core.min(axis=1)).max() <= MAX_CHANNEL_SPREAD
    assert (core @ LUMA).max() <= darkest


def test_the_red_fringe_of_the_pupil_is_covered_too() -> None:
    _, result, distance = _corrected(PUPILS["faded red"][0])
    edge = distance - PUPIL_RADIUS
    fringe = (edge > 0.5) & (edge <= 1.5)
    assert (result[fringe].astype(float) @ LUMA).mean() <= MAX_FRINGE_KEEP * float(
        np.array(SKIN) @ LUMA
    )


def test_the_pupil_edge_is_feathered() -> None:
    _, result, _ = _corrected(PUPILS["faded red"][0])
    row = result[CENTRE].astype(float) @ LUMA
    step = np.abs(np.diff(row)).max()
    assert step <= MAX_EDGE_STEP * (float(np.array(SKIN) @ LUMA) - row[CENTRE])


@pytest.mark.parametrize("pupil", [p for p, _ in PUPILS.values()], ids=PUPILS.keys())
def test_no_dark_halo_around_the_corrected_pupil(pupil: tuple[int, int, int]) -> None:
    img, result, distance = _corrected(pupil)
    edge = distance - PUPIL_RADIUS
    ring = (edge >= HALO_NEAR_PX) & (edge <= HALO_FAR_PX)
    skin_luminance = float(np.array(SKIN) @ LUMA)
    assert (result[ring].astype(float) @ LUMA).mean() >= MIN_RING_KEEP * skin_luminance
    far = edge > UNTOUCHED_BEYOND_PX
    assert np.array_equal(result[far], img[far])
