import dataclasses
import logging
import math

import cv2
import numpy as np
import pytest

from fastfoto_linux.enhance.faces import Face, FaceDetector
from fastfoto_linux.enhance.redeye import (
    HIGHLIGHT_MIN_LEVEL,
    LANDMARK_DISC_FRACTION,
    MIN_INTEROCULAR_MM,
    ROI_HALF_FRACTION,
    EyeFix,
    apply_fixes,
    detect_faces_full_res,
    find_red_eyes,
    remove_red_eye,
)
from tests.face_images import (
    gradient_background,
    load_astronaut,
    photo_with_face,
    scaled_face,
    textured_photo_without_faces,
)

DPI = 300
RED = (230, 20, 20)
PUPIL_FRACTION = 0.07
SPOT_FRACTION = 0.03
MIN_REDNESS_DROP = 0.7
MM_PER_INCH = 25.4
EYES = slice(0, 2)
MOUTH_AND_NOSE = slice(2, 5)
BIG_CANVAS = (1800, 2400)
BIG_FACE_SCALE = 3
BIG_FACE_ORIGIN = (200, 300)
MAPPING_TOLERANCE = 0.15  # of the inter-ocular distance: detection noise at the working size
LOGGER = "fastfoto_linux.enhance.redeye"


@pytest.fixture(scope="module")
def detector() -> FaceDetector:
    return FaceDetector()


@pytest.fixture(scope="module")
def portrait() -> np.ndarray:
    return load_astronaut()


@pytest.fixture(scope="module")
def portrait_face(detector: FaceDetector, portrait: np.ndarray) -> Face:
    return detector.detect(portrait)[0]


@pytest.fixture(scope="module")
def painted_portrait(portrait: np.ndarray, portrait_face: Face) -> np.ndarray:
    return _paint_discs(portrait, _eye_discs(portrait_face, PUPIL_FRACTION))


def _interocular(face: Face) -> float:
    (x0, y0), (x1, y1) = face.landmarks[EYES]
    return math.hypot(x1 - x0, y1 - y0)


def _eye_discs(face: Face, fraction: float) -> list[tuple[tuple[int, int], int]]:
    radius = max(1, round(fraction * _interocular(face)))
    return [((round(x), round(y)), radius) for x, y in face.landmarks[EYES]]


def _paint_discs(
    img: np.ndarray, discs: list[tuple[tuple[int, int], int]], colour: tuple[int, int, int] = RED
) -> np.ndarray:
    painted = img.copy()
    for centre, radius in discs:
        cv2.circle(painted, centre, radius, colour, thickness=-1)
    return painted


def _disc_mask(shape: tuple[int, ...], discs: list[tuple[tuple[int, int], int]]) -> np.ndarray:
    mask = np.zeros(shape[:2], dtype=np.uint8)
    for centre, radius in discs:
        cv2.circle(mask, centre, radius, 1, thickness=-1)
    return mask.astype(bool)


def _redness(img: np.ndarray, where: np.ndarray) -> float:
    pixels = img[where].astype(int)
    return float(np.clip(pixels[:, 0] - pixels[:, 1:].max(axis=1), 0, None).sum())


def _roi_union(shape: tuple[int, ...], fixes: tuple[EyeFix, ...]) -> np.ndarray:
    inside = np.zeros(shape[:2], dtype=bool)
    for fix in fixes:
        x0, y0, x1, y1 = fix.roi
        inside[y0:y1, x0:x1] = True
    return inside


def _changed(before: np.ndarray, after: np.ndarray) -> np.ndarray:
    return np.any(before != after, axis=2)


def test_red_pupils_lose_their_redness(
    detector: FaceDetector, painted_portrait: np.ndarray, portrait_face: Face
) -> None:
    original = painted_portrait.copy()
    result = remove_red_eye(painted_portrait, DPI, detector)
    pupils = _disc_mask(painted_portrait.shape, _eye_discs(portrait_face, PUPIL_FRACTION))
    drop = 1 - _redness(result, pupils) / _redness(painted_portrait, pupils)
    assert drop >= MIN_REDNESS_DROP, f"redness only dropped {drop:.0%}"
    assert result.shape == painted_portrait.shape
    assert result.dtype == np.uint8
    assert np.array_equal(painted_portrait, original)


def test_pixels_outside_the_eye_rois_are_bit_identical(
    detector: FaceDetector, painted_portrait: np.ndarray
) -> None:
    fixes = find_red_eyes(painted_portrait, detect_faces_full_res(painted_portrait, detector))
    result = remove_red_eye(painted_portrait, DPI, detector)
    changed = _changed(painted_portrait, result)
    assert len(fixes) == 2
    assert changed.any()
    assert not changed[~_roi_union(painted_portrait.shape, fixes)].any()


def test_portrait_without_red_pupils_is_unchanged(
    detector: FaceDetector, portrait: np.ndarray
) -> None:
    result = remove_red_eye(portrait, DPI, detector)
    assert np.abs(result.astype(int) - portrait.astype(int)).max() <= 1


def test_big_red_object_without_a_face_is_unchanged(detector: FaceDetector) -> None:
    photo = gradient_background(400, 500)
    photo[100:300, 150:400] = RED
    result = remove_red_eye(photo, DPI, detector)
    assert np.array_equal(result, photo)
    assert result is not photo


def test_red_patches_on_mouth_and_nose_are_unchanged(
    detector: FaceDetector, portrait: np.ndarray, portrait_face: Face
) -> None:
    radius = round(PUPIL_FRACTION * _interocular(portrait_face))
    discs = [((round(x), round(y)), radius) for x, y in portrait_face.landmarks[MOUTH_AND_NOSE]]
    painted = _paint_discs(portrait, discs)
    assert find_red_eyes(painted, (portrait_face,)) == ()
    assert np.array_equal(remove_red_eye(painted, DPI, detector), painted)


def test_large_photo_is_corrected_at_full_resolution(detector: FaceDetector) -> None:
    clean = photo_with_face(*BIG_CANVAS, BIG_FACE_SCALE, BIG_FACE_ORIGIN)
    direct = detector.detect(clean)[0]
    mapped = detect_faces_full_res(clean, detector)
    assert len(mapped) == 1
    tolerance = MAPPING_TOLERANCE * _interocular(direct)
    for want, got in zip(direct.landmarks, mapped[0].landmarks, strict=True):
        assert math.dist(want, got) <= tolerance
    discs = _eye_discs(direct, PUPIL_FRACTION)
    painted = _paint_discs(clean, discs)
    result = remove_red_eye(painted, DPI, detector)
    pupils = _disc_mask(painted.shape, discs)
    drop = 1 - _redness(result, pupils) / _redness(painted, pupils)
    assert drop >= MIN_REDNESS_DROP, f"redness only dropped {drop:.0%}"
    fixes = find_red_eyes(painted, detect_faces_full_res(painted, detector))
    assert not _changed(painted, result)[~_roi_union(painted.shape, fixes)].any()


def test_faces_scoring_below_the_floor_are_ignored(
    painted_portrait: np.ndarray, portrait_face: Face
) -> None:
    assert len(find_red_eyes(painted_portrait, (portrait_face,))) == 2
    unsure = dataclasses.replace(portrait_face, score=0.5)
    assert find_red_eyes(painted_portrait, (unsure,)) == ()


def test_a_red_area_filling_the_roi_is_not_a_pupil(
    portrait: np.ndarray, portrait_face: Face
) -> None:
    flushed = _paint_discs(portrait, _eye_discs(portrait_face, 2 * ROI_HALF_FRACTION))
    assert find_red_eyes(flushed, (portrait_face,)) == ()


def test_a_single_red_pixel_is_not_a_pupil(portrait: np.ndarray, portrait_face: Face) -> None:
    specks = portrait.copy()
    for x, y in portrait_face.landmarks[EYES]:
        specks[round(y), round(x)] = RED
    assert find_red_eyes(specks, (portrait_face,)) == ()


def test_red_inside_the_roi_but_away_from_the_landmark_is_ignored(detector: FaceDetector) -> None:
    portrait = scaled_face(2)
    face = detector.detect(portrait)[0]
    iod = _interocular(face)
    radius = round(SPOT_FRACTION * iod)

    def spots(offset_fraction: float) -> np.ndarray:
        discs = [
            ((round(x + offset_fraction * iod), round(y)), radius) for x, y in face.landmarks[EYES]
        ]
        return _paint_discs(portrait, discs)

    far = 0.8 * ROI_HALF_FRACTION
    assert far - SPOT_FRACTION > LANDMARK_DISC_FRACTION
    assert len(find_red_eyes(spots(0.5 * LANDMARK_DISC_FRACTION), (face,))) == 2
    assert find_red_eyes(spots(far), (face,)) == ()


def test_eye_roi_is_clipped_at_the_image_border(portrait: np.ndarray, portrait_face: Face) -> None:
    cut = round(portrait_face.landmarks[0][0]) - 5
    cropped = portrait[:, cut:].copy()
    shifted = dataclasses.replace(
        portrait_face,
        x=portrait_face.x - cut,
        landmarks=tuple((x - cut, y) for x, y in portrait_face.landmarks),
    )
    painted = _paint_discs(cropped, _eye_discs(shifted, PUPIL_FRACTION))
    fixes = find_red_eyes(painted, (shifted,))
    assert len(fixes) == 2
    assert any(fix.roi[0] == 0 for fix in fixes)
    for fix in fixes:
        x0, y0, x1, y1 = fix.roi
        assert 0 <= x0 < x1 <= painted.shape[1]
        assert 0 <= y0 < y1 <= painted.shape[0]
        assert fix.mask.shape == (y1 - y0, x1 - x0)
        assert fix.mask.dtype == bool
        assert not fix.mask.flags.writeable
        assert fix.mask.any()
    corrected = apply_fixes(painted, fixes)
    assert not _changed(painted, corrected)[~_roi_union(painted.shape, fixes)].any()


def test_specular_highlight_in_the_pupil_is_kept(
    detector: FaceDetector, painted_portrait: np.ndarray, portrait_face: Face
) -> None:
    x, y = (round(v) for v in portrait_face.landmarks[0])
    shiny = painted_portrait.copy()
    shiny[y, x] = (255, HIGHLIGHT_MIN_LEVEL + 40, HIGHLIGHT_MIN_LEVEL + 40)
    result = remove_red_eye(shiny, DPI, detector)
    assert np.array_equal(result[y, x], shiny[y, x])
    assert _changed(shiny, result).any()


def test_apply_fixes_feathers_the_edge_and_spares_the_rest() -> None:
    size = 41
    img = np.full((size, size, 3), (200, 40, 40), dtype=np.uint8)
    disc = np.zeros((size, size), dtype=np.uint8)
    cv2.circle(disc, (size // 2, size // 2), 6, 1, thickness=-1)
    mask = disc.astype(bool)
    mask.setflags(write=False)
    fix = EyeFix(roi=(0, 0, size, size), mask=mask, center=(size // 2, size // 2))
    original = img.copy()
    result = apply_fixes(img, (fix,))
    assert np.array_equal(img, original)
    assert result is not img
    assert result[size // 2, size // 2, 0] < 100
    assert np.array_equal(result[0, 0], img[0, 0])
    feather = _changed(img, result) & ~mask
    assert feather.any()
    ring_red = result[feather][:, 0]
    assert ((ring_red > result[size // 2, size // 2, 0]) & (ring_red < img[0, 0, 0])).any()


def test_apply_fixes_without_fixes_returns_a_copy(portrait: np.ndarray) -> None:
    result = apply_fixes(portrait, ())
    assert np.array_equal(result, portrait)
    assert result is not portrait


def test_read_only_input_is_accepted(detector: FaceDetector, painted_portrait: np.ndarray) -> None:
    frozen = painted_portrait.copy()
    frozen.setflags(write=False)
    result = remove_red_eye(frozen, DPI, detector)
    assert result.flags.writeable
    assert _changed(frozen, result).any()


def test_default_detector_is_used_when_none_is_given(painted_portrait: np.ndarray) -> None:
    result = remove_red_eye(painted_portrait, DPI)
    assert _changed(painted_portrait, result).any()


def test_faces_too_small_for_the_resolution_are_skipped(
    detector: FaceDetector, painted_portrait: np.ndarray, portrait_face: Face
) -> None:
    dpi = math.ceil(2 * _interocular(portrait_face) * MM_PER_INCH / MIN_INTEROCULAR_MM)
    assert np.array_equal(remove_red_eye(painted_portrait, dpi, detector), painted_portrait)


def test_logs_how_many_eyes_were_corrected(
    detector: FaceDetector, painted_portrait: np.ndarray, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger=LOGGER):
        remove_red_eye(painted_portrait, DPI, detector)
    assert "corrected 2 eye" in caplog.text


def test_photo_without_faces_is_returned_as_a_copy(detector: FaceDetector) -> None:
    photo = textured_photo_without_faces(300, 400)
    result = remove_red_eye(photo, DPI, detector)
    assert np.array_equal(result, photo)
    assert result is not photo


@pytest.mark.parametrize("dpi", [0, -300])
def test_dpi_must_be_positive(portrait: np.ndarray, dpi: int) -> None:
    with pytest.raises(ValueError, match="dpi"):
        remove_red_eye(portrait, dpi)


@pytest.mark.parametrize(
    "bad",
    [
        np.zeros((10, 10), np.uint8),
        np.zeros((10, 10, 3), np.float32),
        np.zeros((0, 4, 3), np.uint8),
    ],
)
def test_images_must_be_rgb_uint8(bad: np.ndarray) -> None:
    for call in (
        lambda: remove_red_eye(bad, DPI),
        lambda: find_red_eyes(bad, ()),
        lambda: apply_fixes(bad, ()),
        lambda: detect_faces_full_res(bad),
    ):
        with pytest.raises(ValueError, match="RGB uint8"):
            call()


def test_non_array_input_is_rejected() -> None:
    with pytest.raises(TypeError, match="numpy array"):
        remove_red_eye([[0, 0, 0]], DPI)  # type: ignore[arg-type]
