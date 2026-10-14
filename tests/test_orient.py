import dataclasses

import numpy as np
import pytest

from fastfoto_linux.enhance.faces import FaceDetector
from fastfoto_linux.enhance.orient import (
    _CV2_ROTATION_CODE,
    CANDIDATE_ROTATIONS,
    OrientationDecision,
    _choose_rotation,
    _rotation_score,
    apply_rotation,
    auto_orient,
    decide_orientation,
)
from tests.face_images import (
    load_astronaut,
    photo_with_face,
    photo_with_two_faces,
    textured_photo_without_faces,
)

DPI = 600
# Scores below are binary-exact fractions so the 1.5x boundary is not hit by rounding error.
STRONG = 0.375
WEAK = 0.0625
UPRIGHT_PHOTOS = {
    "landscape": lambda: photo_with_face(1200, 1600, 2, (100, 900)),
    "small": lambda: photo_with_face(900, 1200, 1, (300, 400)),
    "bare-portrait": load_astronaut,
}


@pytest.fixture(scope="module")
def detector() -> FaceDetector:
    return FaceDetector()


@pytest.fixture(params=sorted(UPRIGHT_PHOTOS))
def upright(request: pytest.FixtureRequest) -> np.ndarray:
    return UPRIGHT_PHOTOS[request.param]()


# --- pure decision rule -------------------------------------------------------------------


@pytest.mark.parametrize("index", range(len(CANDIDATE_ROTATIONS)))
def test_rule_picks_the_clearly_best_rotation(index: int) -> None:
    scores = [0.0] * len(CANDIDATE_ROTATIONS)
    scores[index] = STRONG
    assert _choose_rotation(scores) == CANDIDATE_ROTATIONS[index]


def test_rule_needs_a_minimum_absolute_score() -> None:
    assert _choose_rotation([WEAK, 0.0, 0.0, 0.0]) is None
    assert _choose_rotation([0.125, 0.0, 0.0, 0.0]) == 0


def test_rule_needs_a_margin_over_the_runner_up() -> None:
    assert _choose_rotation([0.0, STRONG, 0.25, 0.0]) == 90  # exactly 1.5x is enough
    assert _choose_rotation([0.0, STRONG, 0.28125, 0.0]) is None
    assert _choose_rotation([0.25, 0.0, 0.25, 0.0]) is None


def test_rule_says_unknown_when_nothing_was_found() -> None:
    assert _choose_rotation([0.0, 0.0, 0.0, 0.0]) is None


# --- end to end on real face detection ------------------------------------------------------


@pytest.mark.parametrize("quarter_turns", range(4))
def test_every_rotation_is_detected_and_undone_exactly(
    upright: np.ndarray, detector: FaceDetector, quarter_turns: int
) -> None:
    # np.rot90 turns counter-clockwise, so undoing it needs the same number of clockwise turns.
    turned = np.ascontiguousarray(np.rot90(upright, quarter_turns))
    decision = decide_orientation(turned, DPI, detector)
    assert decision.rotation == 90 * quarter_turns
    assert decision.confident
    assert np.array_equal(auto_orient(turned, DPI, detector), upright)


def test_decision_carries_one_score_per_candidate_rotation(detector: FaceDetector) -> None:
    decision = decide_orientation(load_astronaut(), DPI, detector)
    assert len(decision.scores) == len(CANDIDATE_ROTATIONS)
    assert decision.scores[0] == max(decision.scores)
    with pytest.raises(dataclasses.FrozenInstanceError):
        decision.rotation = 90  # type: ignore[misc]


def test_default_detector_is_used_when_none_is_given() -> None:
    decision = decide_orientation(load_astronaut(), DPI)
    assert decision.rotation == 0
    assert decision.confident


def test_photo_without_faces_is_left_alone(detector: FaceDetector) -> None:
    photo = textured_photo_without_faces(1200, 1600)
    original = photo.copy()
    decision = decide_orientation(photo, DPI, detector)
    assert decision == OrientationDecision(rotation=0, scores=(0.0, 0.0, 0.0, 0.0), confident=False)
    result = auto_orient(photo, DPI, detector)
    assert np.array_equal(result, original)
    assert result is not photo
    assert np.array_equal(photo, original)


def test_ambiguous_photo_is_left_alone(detector: FaceDetector) -> None:
    photo = photo_with_two_faces(800, 1600)
    decision = decide_orientation(photo, DPI, detector)
    assert decision.rotation == 0
    assert not decision.confident
    assert np.array_equal(auto_orient(photo, DPI, detector), photo)


def test_orientation_does_not_mutate_a_read_only_input(detector: FaceDetector) -> None:
    turned = np.ascontiguousarray(np.rot90(photo_with_face(900, 1200, 1, (300, 400)), 1))
    original = turned.copy()
    turned.setflags(write=False)
    result = auto_orient(turned, DPI, detector)
    assert np.array_equal(turned, original)
    assert result.flags.writeable
    assert not np.shares_memory(result, turned)


# --- rotation helper and input validation ---------------------------------------------------


@pytest.mark.parametrize(("rotation", "quarter_turns"), [(0, 0), (90, 3), (180, 2), (270, 1)])
def test_apply_rotation_is_clockwise(rotation: int, quarter_turns: int) -> None:
    image = np.arange(2 * 3 * 3, dtype=np.uint8).reshape(2, 3, 3)
    result = apply_rotation(image, rotation)
    assert np.array_equal(result, np.rot90(image, quarter_turns))
    assert not np.shares_memory(result, image)


def test_apply_rotation_rejects_other_angles() -> None:
    with pytest.raises(ValueError, match="rotation"):
        apply_rotation(np.zeros((4, 4, 3), dtype=np.uint8), 45)


@pytest.mark.parametrize("dpi", [0, -600])
def test_dpi_must_be_positive(dpi: int) -> None:
    with pytest.raises(ValueError, match="dpi"):
        decide_orientation(load_astronaut(), dpi)


def test_image_must_be_rgb_uint8() -> None:
    with pytest.raises(ValueError, match="RGB"):
        decide_orientation(np.zeros((10, 10), dtype=np.uint8), DPI)
    with pytest.raises(ValueError, match="RGB"):
        auto_orient(np.zeros((10, 10, 3), dtype=np.float32), DPI)


@pytest.mark.parametrize("shape", [(2, 5000, 3), (1, 3000, 3), (5000, 2, 3)])
def test_thin_images_are_left_alone(shape: tuple[int, int, int], detector: FaceDetector) -> None:
    thin = np.full(shape, 128, dtype=np.uint8)
    decision = decide_orientation(thin, DPI, detector)
    assert decision == OrientationDecision(rotation=0, scores=(0.0, 0.0, 0.0, 0.0), confident=False)
    assert np.array_equal(auto_orient(thin, DPI, detector), thin)


def test_faces_below_the_confidence_floor_contribute_nothing(detector: FaceDetector) -> None:
    upside_down = np.ascontiguousarray(np.rot90(load_astronaut(), 2))
    assert detector.detect(upside_down)  # seen by the detector...
    assert _rotation_score(detector, upside_down, 0) == 0.0  # ...but worth nothing here


def test_rotation_table_is_read_only() -> None:
    with pytest.raises(TypeError):
        _CV2_ROTATION_CODE[90] = 0  # type: ignore[index]
