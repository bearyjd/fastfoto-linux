"""Why red blobs near an eye are rejected: shape, position and contrast gates."""

import dataclasses
import logging
import math

import cv2
import numpy as np
import pytest

from fastfoto_linux.enhance.faces import Face, FaceDetector
from fastfoto_linux.enhance.redeye import ROI_HALF_FRACTION, _ring_contrast, find_red_eyes
from tests.face_images import scaled_face

LOGGER = "fastfoto_linux.enhance.redeye"
EYES = slice(0, 2)
RED = (230, 20, 20)
PUPIL_RADIUS_FRACTION = 0.04
BAR_LENGTH_FRACTION = 0.2
BAR_THICKNESS_PX = 3
STRIPE_WIDTH_PX = 4
# A loose-red disc (redness 59, ratio 1.42) around a tiny strictly-red core: grown into a pupil.
LOOSE_RED = (200, 141, 135)
LOOSE_RADIUS_FRACTION = 0.08
CORE_RADIUS_PX = 1
# Surroundings that are not loosely red but almost as red as the disc, or plainly neutral.
REDDISH_SKIN = (200, 150, 145)
NEUTRAL_SKIN = (200, 190, 185)
BIG_BLOB_RADIUS_FRACTION = 0.18  # inside the ROI (half-size 0.25) but far wider than a pupil
# Reds that are not saturated enough for a pupil: flushed skin, and dark brown lashes or brows.
NOT_PUPIL_COLOURS = {"flushed skin": (230, 150, 140), "dark brown": (110, 45, 35)}


@pytest.fixture(scope="module")
def portrait() -> np.ndarray:
    return scaled_face(2)


@pytest.fixture(scope="module")
def face(portrait: np.ndarray) -> Face:
    return FaceDetector().detect(portrait)[0]


def _interocular(face: Face) -> float:
    (x0, y0), (x1, y1) = face.landmarks[EYES]
    return math.hypot(x1 - x0, y1 - y0)


def _eyes(face: Face) -> list[tuple[int, int]]:
    return [(round(x), round(y)) for x, y in face.landmarks[EYES]]


def _rejections(caplog: pytest.LogCaptureFixture, reason: str) -> int:
    return sum(reason in record.getMessage() for record in caplog.records)


def test_a_thin_red_bar_is_not_round(
    portrait: np.ndarray, face: Face, caplog: pytest.LogCaptureFixture
) -> None:
    barred = portrait.copy()
    half_length = round(BAR_LENGTH_FRACTION * _interocular(face) / 2)
    for x, y in _eyes(face):
        top_left = (x - half_length, y - BAR_THICKNESS_PX // 2)
        bottom_right = (x + half_length, y + BAR_THICKNESS_PX // 2)
        cv2.rectangle(barred, top_left, bottom_right, RED, thickness=-1)
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        assert find_red_eyes(barred, (face,)) == ()
    assert _rejections(caplog, "not round") == 2


def test_a_red_stripe_across_the_whole_roi_is_not_a_pupil(
    portrait: np.ndarray, face: Face, caplog: pytest.LogCaptureFixture
) -> None:
    reach = round(ROI_HALF_FRACTION * _interocular(face)) + STRIPE_WIDTH_PX
    striped = portrait.copy()
    for x, y in _eyes(face):
        cv2.rectangle(striped, (x - 1, y - reach), (x + 1, y + reach), RED, thickness=-1)
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        assert find_red_eyes(striped, (face,)) == ()
    assert _rejections(caplog, "touches the ROI edge") == 2


def test_a_wide_red_blob_inside_the_roi_is_too_large_for_a_pupil(
    portrait: np.ndarray, face: Face, caplog: pytest.LogCaptureFixture
) -> None:
    blotchy = portrait.copy()
    radius = round(BIG_BLOB_RADIUS_FRACTION * _interocular(face))
    for centre in _eyes(face):
        cv2.circle(blotchy, centre, radius, RED, thickness=-1)
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        assert find_red_eyes(blotchy, (face,)) == ()
    assert _rejections(caplog, "too large") == 2


@pytest.mark.parametrize("colour", NOT_PUPIL_COLOURS.values(), ids=NOT_PUPIL_COLOURS.keys())
def test_reds_that_are_not_saturated_enough_are_ignored(
    portrait: np.ndarray, face: Face, colour: tuple[int, int, int]
) -> None:
    radius = round(PUPIL_RADIUS_FRACTION * _interocular(face))
    painted = portrait.copy()
    for centre in _eyes(face):
        cv2.circle(painted, centre, radius, colour, thickness=-1)
    assert find_red_eyes(painted, (face,)) == ()


def test_a_two_pixel_speck_is_noise_even_in_a_tiny_face(portrait: np.ndarray) -> None:
    tiny = Face(
        x=90.0,
        y=90.0,
        width=40.0,
        height=40.0,
        landmarks=((100.0, 100.0), (123.0, 100.0), (111.0, 112.0), (104.0, 122.0), (118.0, 122.0)),
        score=0.9,
    )
    specked = portrait.copy()
    specked[100, 100:102] = RED
    assert find_red_eyes(specked, (tiny,)) == ()


def test_eyes_outside_the_image_are_skipped(portrait: np.ndarray, face: Face) -> None:
    far = 10 * portrait.shape[1]
    stray = dataclasses.replace(
        face, landmarks=tuple((x - far, y) for x, y in face.landmarks), x=face.x - far
    )
    assert find_red_eyes(portrait, (stray,)) == ()


def _core_on_loose_red(
    portrait: np.ndarray, face: Face, surroundings: tuple[int, int, int]
) -> np.ndarray:
    iod = _interocular(face)
    painted = portrait.copy()
    for centre in _eyes(face):
        cv2.circle(painted, centre, math.ceil(ROI_HALF_FRACTION * iod), surroundings, -1)
        cv2.circle(painted, centre, round(LOOSE_RADIUS_FRACTION * iod), LOOSE_RED, -1)
        cv2.circle(painted, centre, CORE_RADIUS_PX, RED, -1)
    return painted


def test_a_blob_as_red_as_its_surroundings_is_not_a_pupil(
    portrait: np.ndarray, face: Face, caplog: pytest.LogCaptureFixture
) -> None:
    flushed = _core_on_loose_red(portrait, face, REDDISH_SKIN)
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        assert find_red_eyes(flushed, (face,)) == ()
    assert _rejections(caplog, "not redder than its surroundings") == 2


def test_the_same_blob_on_neutral_skin_is_a_pupil(portrait: np.ndarray, face: Face) -> None:
    fixes = find_red_eyes(_core_on_loose_red(portrait, face, NEUTRAL_SKIN), (face,))
    assert len(fixes) == 2
    assert all(fix.mask.sum() > math.pi * CORE_RADIUS_PX**2 for fix in fixes)


def test_a_blob_filling_the_patch_has_no_ring_to_compare_with() -> None:
    patch = np.full((9, 9, 3), RED, dtype=np.uint8)
    assert _ring_contrast(patch, np.ones((9, 9), dtype=bool)) is None
