"""Why red blobs near an eye are rejected: shape, position and contrast gates."""

import dataclasses
import logging
import math

import cv2
import numpy as np
import pytest

from fastfoto_linux.enhance.faces import Face, FaceDetector
from fastfoto_linux.enhance.redeye import (
    ROI_HALF_FRACTION,
    EyeFix,
    _grow_pupil,
    _ring_contrast,
    apply_fixes,
    find_red_eyes,
    remove_red_eye,
)
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
MODERATE_SKIN = (200, 165, 160)  # redness 35: the blob still stands out by about 28
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
    specked[100:102, 100] = RED
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


def test_a_blob_filling_the_patch_has_no_contrast_with_its_surroundings() -> None:
    patch = np.full((9, 9, 3), RED, dtype=np.uint8)
    assert _ring_contrast(patch, np.ones((9, 9), dtype=bool)) == 0.0


def _blocks(portrait: np.ndarray, face: Face, width: int, height: int) -> np.ndarray:
    """A filled red rectangle of ``width`` x ``height`` pixels centred on each eye."""
    painted = portrait.copy()
    for x, y in _eyes(face):
        left, top = x - width // 2, y - height // 2
        cv2.rectangle(painted, (left, top), (left + width - 1, top + height - 1), RED, -1)
    return painted


def test_a_blob_wider_than_tall_is_not_a_pupil(portrait: np.ndarray, face: Face) -> None:
    assert len(find_red_eyes(_blocks(portrait, face, 8, 8), (face,))) == 2
    assert len(find_red_eyes(_blocks(portrait, face, 10, 8), (face,))) == 2
    assert find_red_eyes(_blocks(portrait, face, 11, 8), (face,)) == ()


def test_a_blob_somewhat_taller_than_wide_is_still_a_pupil(
    portrait: np.ndarray, face: Face
) -> None:
    assert len(find_red_eyes(_blocks(portrait, face, 6, 10), (face,))) == 2


def test_a_blob_far_taller_than_wide_is_not_a_pupil(portrait: np.ndarray, face: Face) -> None:
    assert find_red_eyes(_blocks(portrait, face, 4, 12), (face,)) == ()


def test_a_hollow_square_is_not_a_pupil(portrait: np.ndarray, face: Face) -> None:
    hollow = portrait.copy()
    for x, y in _eyes(face):
        cv2.rectangle(hollow, (x - 6, y - 6), (x + 5, y + 5), RED, thickness=1)
    assert find_red_eyes(hollow, (face,)) == ()


@pytest.mark.parametrize(("level", "found"), [(90, 2), (89, 0)])
def test_red_level_boundary(portrait: np.ndarray, face: Face, level: int, found: int) -> None:
    radius = round(PUPIL_RADIUS_FRACTION * _interocular(face))
    painted = portrait.copy()
    for centre in _eyes(face):
        cv2.circle(painted, centre, radius, (level, 15, 15), thickness=-1)
    assert len(find_red_eyes(painted, (face,))) == found


@pytest.mark.parametrize(("score", "found"), [(0.9, 2), (0.89, 0), (0.5, 0)])
def test_face_score_boundary(portrait: np.ndarray, face: Face, score: float, found: int) -> None:
    painted = portrait.copy()
    radius = round(PUPIL_RADIUS_FRACTION * _interocular(face))
    for centre in _eyes(face):
        cv2.circle(painted, centre, radius, RED, thickness=-1)
    sure = dataclasses.replace(face, score=score)
    assert len(find_red_eyes(painted, (sure,))) == found


def _with_landmarks(face: Face, landmarks: tuple[tuple[float, float], ...]) -> Face:
    return dataclasses.replace(face, landmarks=landmarks)


def test_a_face_needs_two_eye_landmarks(portrait: np.ndarray, face: Face) -> None:
    for landmarks in ((), face.landmarks[:1]):
        with pytest.raises(ValueError, match="landmarks"):
            find_red_eyes(portrait, (_with_landmarks(face, landmarks),))


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_eye_landmarks_must_be_finite(portrait: np.ndarray, face: Face, bad: float) -> None:
    broken = _with_landmarks(face, ((bad, 5.0), *face.landmarks[1:]))
    with pytest.raises(ValueError, match="finite"):
        find_red_eyes(portrait, (broken,))


def test_the_mask_must_match_the_roi() -> None:
    wrong_shape = np.ones((3, 3), dtype=bool)
    with pytest.raises(ValueError, match="mask"):
        EyeFix(roi=(0, 0, 4, 4), mask=wrong_shape, center=(1.0, 1.0))
    with pytest.raises(ValueError, match="mask"):
        EyeFix(roi=(0, 0, 3, 3), mask=np.ones((3, 3), dtype=np.uint8), center=(1.0, 1.0))
    with pytest.raises(ValueError, match="ROI"):
        EyeFix(roi=(2, 2, 2, 5), mask=np.ones((3, 0), dtype=bool), center=(1.0, 1.0))


def test_fixes_must_lie_inside_the_image(portrait: np.ndarray) -> None:
    width = portrait.shape[1]
    outside = EyeFix(
        roi=(width - 2, 0, width + 2, 4), mask=np.ones((4, 4), dtype=bool), center=(0.0, 0.0)
    )
    with pytest.raises(ValueError, match="ROI"):
        apply_fixes(portrait, (outside,))


@pytest.mark.parametrize("dpi", [math.nan, math.inf, -math.inf, True, False])
def test_dpi_must_be_a_positive_finite_number(portrait: np.ndarray, dpi: float) -> None:
    with pytest.raises(ValueError, match="dpi"):
        remove_red_eye(portrait, dpi)  # type: ignore[arg-type]


def test_a_dot_far_smaller_than_the_roi_is_noise(portrait: np.ndarray, face: Face) -> None:
    assert len(find_red_eyes(_blocks(portrait, face, 2, 2), (face,))) == 0
    assert len(find_red_eyes(_blocks(portrait, face, 5, 5), (face,))) == 2


def test_a_blob_moderately_redder_than_its_surroundings_is_a_pupil(
    portrait: np.ndarray, face: Face
) -> None:
    assert len(find_red_eyes(_core_on_loose_red(portrait, face, MODERATE_SKIN), (face,))) == 2


def test_the_roi_is_a_square_centred_on_the_eye(portrait: np.ndarray, face: Face) -> None:
    half = round(ROI_HALF_FRACTION * _interocular(face))
    fixes = find_red_eyes(_blocks(portrait, face, 8, 8), (face,))
    assert [fix.roi for fix in fixes] == [
        (x - half, y - half, x + half + 1, y + half + 1) for x, y in _eyes(face)
    ]
    assert [fix.center for fix in fixes] == list(face.landmarks[:2])


GROW_SIZE = 41
GROW_CENTRE = GROW_SIZE // 2
GROW_IOD = 60.0  # the growth reach is 0.1 x 60 = 6 px


def _seed_patch(surroundings: tuple[int, int, int]) -> tuple[np.ndarray, np.ndarray]:
    patch = np.full((GROW_SIZE, GROW_SIZE, 3), NEUTRAL_SKIN, dtype=np.uint8)
    seed = np.zeros((GROW_SIZE, GROW_SIZE), dtype=bool)
    seed[GROW_CENTRE - 1 : GROW_CENTRE + 2, GROW_CENTRE - 1 : GROW_CENTRE + 2] = True
    patch[seed] = RED
    patch[GROW_CENTRE - 3 : GROW_CENTRE + 4, GROW_CENTRE - 3 : GROW_CENTRE + 4][
        ~seed[GROW_CENTRE - 3 : GROW_CENTRE + 4, GROW_CENTRE - 3 : GROW_CENTRE + 4]
    ] = surroundings
    return patch, seed


def test_growth_stops_at_the_pupil_radius() -> None:
    patch, seed = _seed_patch(LOOSE_RED)
    patch[GROW_CENTRE - 1 : GROW_CENTRE + 2, GROW_CENTRE:] = LOOSE_RED  # a tail to the right edge
    grown = _grow_pupil(patch, seed, GROW_IOD)
    xs = np.nonzero(grown)[1]
    assert xs.max() <= GROW_CENTRE + 6
    assert xs.max() > GROW_CENTRE + 3


def test_growth_only_takes_pixels_connected_to_the_seed() -> None:
    patch, seed = _seed_patch(LOOSE_RED)
    patch[GROW_CENTRE, GROW_CENTRE + 5 : GROW_CENTRE + 7] = LOOSE_RED  # beyond a one-pixel gap
    patch[GROW_CENTRE, GROW_CENTRE + 4] = NEUTRAL_SKIN
    grown = _grow_pupil(patch, seed, GROW_IOD)
    assert not grown[GROW_CENTRE, GROW_CENTRE + 5 : GROW_CENTRE + 7].any()
    assert grown[GROW_CENTRE - 2 : GROW_CENTRE + 3, GROW_CENTRE - 2 : GROW_CENTRE + 3].all()


@pytest.mark.parametrize(("redness", "taken"), [(40, True), (30, False)])
def test_growth_needs_loose_redness(redness: int, taken: bool) -> None:
    surroundings = (100 + redness - 30, 70, 70)  # ratio 1.43..1.57, R >= 90
    patch, seed = _seed_patch(surroundings)
    grown = _grow_pupil(patch, seed, GROW_IOD)
    assert bool(grown.sum() > seed.sum()) is taken


def _crosses(portrait: np.ndarray, face: Face, size: int, arm: int) -> np.ndarray:
    """A red plus sign inside a ``size`` x ``size`` box on each eye, arms ``arm`` pixels thick."""
    painted = portrait.copy()
    for x, y in _eyes(face):
        left, top = x - size // 2, y - size // 2
        offset = (size - arm) // 2
        cv2.rectangle(
            painted, (left, top + offset), (left + size - 1, top + offset + arm - 1), RED, -1
        )
        cv2.rectangle(
            painted, (left + offset, top), (left + offset + arm - 1, top + size - 1), RED, -1
        )
    return painted


def test_a_ragged_blob_is_not_a_pupil_but_a_plump_one_is(portrait: np.ndarray, face: Face) -> None:
    assert find_red_eyes(_crosses(portrait, face, 11, 3), (face,)) == ()  # fills 0.47 of its box
    assert len(find_red_eyes(_crosses(portrait, face, 11, 5), (face,))) == 2  # fills 0.70
