"""Red-eye removal on the enhanced copy of a photo.

Only a small red blob centred on a detected eye landmark is ever changed, so red clothes, lips
and roses are left alone. Faces come from the shared YuNet detector, which finds upright faces
only: orient the photo first (``orient.auto_orient``). Pixels outside the eye regions are
returned bit-identical; the input array is never modified.
"""

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass

import cv2
import numpy as np

from fastfoto_linux.enhance.faces import Face, FaceDetector, ensure_rgb_uint8
from fastfoto_linux.enhance.fullres import detect_faces_full_res

logger = logging.getLogger(__name__)

MM_PER_INCH = 25.4
MIN_FACE_SCORE = 0.9
# Faces whose eyes are closer than this are too small for a pupil to be told from noise.
MIN_INTEROCULAR_MM = 2.0
# Geometry is relative to the inter-ocular distance, so it holds at any scan resolution.
ROI_HALF_FRACTION = 0.25
LANDMARK_DISC_FRACTION = 0.1
# A pixel is red when R is high, well above G and B, and more than the dominance times both.
# Seeds use a strict test (warm skin, eyelid shadows and brows in faded prints pass weaker ones);
# the pupil is then grown from its seed with a looser test, within PUPIL_RADIUS_FRACTION of it,
# because faded red pupils are only strongly red at their core.
MIN_RED_LEVEL = 90
SEED_MIN_REDNESS = 70
SEED_DOMINANCE = 2.0
PUPIL_MIN_REDNESS = 40
PUPIL_DOMINANCE = 1.4
PUPIL_RADIUS_FRACTION = 0.1
# A pupil is a small, compact, round blob that stays clear of the ROI edge and is redder than
# the ring around it. Area bounds are a fraction of the ROI area (plus an absolute pixel floor).
MIN_AREA_FRACTION = 0.01
MIN_COMPONENT_PIXELS = 4
MAX_AREA_FRACTION = 0.10
# Photos are upright by now, so lash and lid lines are wide: a pupil is never wider than tall.
MAX_WIDTH_OVER_HEIGHT = 1.25
MAX_HEIGHT_OVER_WIDTH = 2.0
MIN_FILL_RATIO = 0.5
MIN_RING_CONTRAST = 20
RING_INNER_FRACTION = 0.5
RING_OUTER_FRACTION = 2.0
# Pupils are small and round: grow the mask and feather it in proportion to the pupil radius.
GROW_FRACTION = 0.1
FEATHER_FRACTION = 0.15
MIN_FEATHER_SIGMA_PX = 0.5
# Pixels with both G and B at least this bright are specular highlights and stay as they are.
HIGHLIGHT_MIN_LEVEL = 200
# Corrected pupils are a neutral dark grey: half the blue-green level, never above this.
DARKEN = 0.5
PUPIL_MAX_LEVEL = 40
LANDMARKS_PER_FACE = 2  # right eye, left eye: the first two YuNet landmarks
MAX_LEVEL = 255

_REASON_TOO_SMALL = "too small"
_REASON_TOO_LARGE = "too large"
_REASON_AT_EDGE = "touches the ROI edge"
_REASON_NOT_ROUND = "not round"
_REASON_NOT_RED_ENOUGH = "not redder than its surroundings"


@dataclass(frozen=True, eq=False)
class EyeFix:
    """One red pupil to correct.

    ``roi`` is (x0, y0, x1, y1) in image pixels, x1/y1 exclusive; ``mask`` is a read-only
    boolean array of the ROI's shape marking the red component; ``center`` is the eye landmark.
    """

    roi: tuple[int, int, int, int]
    mask: np.ndarray
    center: tuple[float, float]

    def __post_init__(self) -> None:
        x0, y0, x1, y1 = self.roi
        if x0 < 0 or y0 < 0 or x1 <= x0 or y1 <= y0:
            raise ValueError(
                f"ROI must be a non-empty box with non-negative origin, got {self.roi}"
            )
        shape = (y1 - y0, x1 - x0)
        if self.mask.dtype != bool or self.mask.shape != shape:
            raise ValueError(
                f"mask must be a boolean array of the ROI's shape {shape}, "
                f"got {self.mask.dtype} {self.mask.shape}"
            )


def _mm_to_px(mm: float, dpi: int) -> float:
    return mm * dpi / MM_PER_INCH


def _eye_points(face: Face) -> tuple[tuple[float, float], ...]:
    """The two eye landmarks of ``face``; ``ValueError`` if they are missing or not finite."""
    eyes = face.landmarks[:LANDMARKS_PER_FACE]
    if len(eyes) < LANDMARKS_PER_FACE:
        raise ValueError(
            f"a face needs {LANDMARKS_PER_FACE} eye landmarks, got {len(face.landmarks)}"
        )
    if not all(math.isfinite(v) for point in eyes for v in point):
        raise ValueError(f"eye landmarks must be finite, got {eyes}")
    return eyes


def _interocular(face: Face) -> float:
    (x0, y0), (x1, y1) = _eye_points(face)
    return math.hypot(x1 - x0, y1 - y0)


def _roi_box(
    centre: tuple[float, float], half: int, shape: tuple[int, ...]
) -> tuple[int, int, int, int] | None:
    """The square of half-size ``half`` around ``centre``, clipped to the image; None if empty."""
    height, width = shape[:2]
    x, y = round(centre[0]), round(centre[1])
    x0, y0 = max(0, x - half), max(0, y - half)
    x1, y1 = min(width, x + half + 1), min(height, y + half + 1)
    return (x0, y0, x1, y1) if x0 < x1 and y0 < y1 else None


def _red_mask(patch: np.ndarray, min_redness: int, dominance: float) -> np.ndarray:
    levels = patch.astype(np.int16)
    red = levels[..., 0]
    other = np.maximum(levels[..., 1], levels[..., 2])
    return (red - other >= min_redness) & (red >= MIN_RED_LEVEL) & (red > dominance * other)


def _component_nearest(
    red: np.ndarray, centre: tuple[float, float], radius: float
) -> np.ndarray | None:
    """The connected red component holding the red pixel nearest ``centre``, within ``radius``."""
    ys, xs = np.nonzero(red)
    if ys.size == 0:
        return None
    distance = np.hypot(xs - centre[0], ys - centre[1])
    nearest = int(np.argmin(distance))
    if distance[nearest] > radius:
        return None
    _, labels = cv2.connectedComponents(red.astype(np.uint8), connectivity=8)
    return labels == labels[ys[nearest], xs[nearest]]


def _grow_pupil(patch: np.ndarray, seed: np.ndarray, iod: float) -> np.ndarray:
    """``seed`` plus loosely red pixels connected to it, within the pupil radius of its centre."""
    ys, xs = np.nonzero(seed)
    rows, cols = np.ogrid[: seed.shape[0], : seed.shape[1]]
    reach = (rows - ys.mean()) ** 2 + (cols - xs.mean()) ** 2 <= (PUPIL_RADIUS_FRACTION * iod) ** 2
    allowed = seed | (_red_mask(patch, PUPIL_MIN_REDNESS, PUPIL_DOMINANCE) & reach)
    _, labels = cv2.connectedComponents(allowed.astype(np.uint8), connectivity=8)
    return labels == labels[ys[0], xs[0]]


def _touches_edge(component: np.ndarray) -> bool:
    return bool(
        component[0].any() or component[-1].any() or component[:, 0].any() or component[:, -1].any()
    )


def _is_round(component: np.ndarray) -> bool:
    """True if the blob is no wider than tall, not far taller, and well filled (a disc: ~0.79)."""
    ys, xs = np.nonzero(component)
    width, height = int(xs.max() - xs.min()) + 1, int(ys.max() - ys.min()) + 1
    return (
        width / height <= MAX_WIDTH_OVER_HEIGHT
        and height / width <= MAX_HEIGHT_OVER_WIDTH
        and int(ys.size) / (width * height) >= MIN_FILL_RATIO
    )


def _redness(patch: np.ndarray) -> np.ndarray:
    levels = patch.astype(np.int16)
    return levels[..., 0] - np.maximum(levels[..., 1], levels[..., 2])


def _ring_contrast(patch: np.ndarray, component: np.ndarray) -> float:
    """Mean redness of the blob minus the median redness of the ring around it (0: no ring)."""
    radius = math.sqrt(int(component.sum()) / math.pi)
    mask = component.astype(np.uint8)
    inner, outer = (
        cv2.dilate(
            mask,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * grow + 1, 2 * grow + 1)),
        ).astype(bool)
        for grow in (
            max(1, round(RING_INNER_FRACTION * radius)),
            max(2, round(RING_OUTER_FRACTION * radius)),
        )
    )
    ring = outer & ~inner
    if not ring.any():
        return 0.0
    redness = _redness(patch)
    return float(redness[component].mean() - np.median(redness[ring]))


def _rejection(patch: np.ndarray, component: np.ndarray, roi_area: float) -> str | None:
    """Why a red ``component`` of ``patch`` is not a pupil, or None if it may be one."""
    area = int(component.sum())
    if area < max(MIN_COMPONENT_PIXELS, MIN_AREA_FRACTION * roi_area):
        return _REASON_TOO_SMALL
    if area > MAX_AREA_FRACTION * roi_area:
        return _REASON_TOO_LARGE
    if _touches_edge(component):
        return _REASON_AT_EDGE
    if not _is_round(component):
        return _REASON_NOT_ROUND
    if _ring_contrast(patch, component) < MIN_RING_CONTRAST:
        return _REASON_NOT_RED_ENOUGH
    return None


def _find_pupil(img: np.ndarray, centre: tuple[float, float], iod: float) -> EyeFix | None:
    half = max(1, round(ROI_HALF_FRACTION * iod))
    roi = _roi_box(centre, half, img.shape)
    if roi is None:
        return None
    x0, y0, x1, y1 = roi
    patch = img[y0:y1, x0:x1]
    local = (round(centre[0]) - x0, round(centre[1]) - y0)
    seed = _component_nearest(
        _red_mask(patch, SEED_MIN_REDNESS, SEED_DOMINANCE),
        local,
        max(1.0, LANDMARK_DISC_FRACTION * iod),
    )
    if seed is None:
        return None
    component = _grow_pupil(patch, seed, iod)
    reason = _rejection(patch, component, (2 * half + 1) ** 2)
    if reason is not None:
        logger.debug("red blob near an eye rejected: %s", reason)
        return None
    component.setflags(write=False)
    return EyeFix(roi=roi, mask=component, center=centre)


def find_red_eyes(img: np.ndarray, faces: Sequence[Face]) -> tuple[EyeFix, ...]:
    """The red pupils in ``img`` for ``faces`` (given in ``img`` pixel coordinates).

    Faces scoring below ``MIN_FACE_SCORE`` are ignored.
    """
    ensure_rgb_uint8(img)
    fixes: list[EyeFix] = []
    for face in faces:
        if face.score < MIN_FACE_SCORE:
            continue
        iod = _interocular(face)
        for centre in face.landmarks[:LANDMARKS_PER_FACE]:
            fix = _find_pupil(img, centre, iod)
            if fix is not None:
                fixes.append(fix)
    return tuple(fixes)


def _feathered_alpha(patch: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Blend weights in [0, 1]: the mask grown a little, softened, and zero on highlights."""
    radius = math.sqrt(int(mask.sum()) / math.pi)
    grow = round(GROW_FRACTION * radius)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * grow + 1, 2 * grow + 1))
    grown = cv2.dilate(mask.astype(np.uint8), kernel).astype(np.float32)
    sigma = max(MIN_FEATHER_SIGMA_PX, FEATHER_FRACTION * radius)
    alpha = np.clip(cv2.GaussianBlur(grown, (0, 0), sigma), 0.0, 1.0)
    highlight = patch[..., 1:].min(axis=2) >= HIGHLIGHT_MIN_LEVEL
    alpha[highlight] = 0.0
    return alpha


def _corrected_patch(patch: np.ndarray, mask: np.ndarray, strength: float = 1.0) -> np.ndarray:
    source = patch.astype(np.float32)
    neutral = (source[..., 1] + source[..., 2]) / 2
    level = np.minimum(np.minimum(source[..., 0], neutral) * DARKEN, PUPIL_MAX_LEVEL)
    fixed = np.repeat(level[..., np.newaxis], 3, axis=2)
    alpha = _feathered_alpha(patch, mask)[..., np.newaxis] * strength
    blended = source + alpha * (fixed - source)
    return np.clip(np.rint(blended), 0, MAX_LEVEL).astype(np.uint8)


def apply_fixes(img: np.ndarray, fixes: Sequence[EyeFix], *, strength: float = 1.0) -> np.ndarray:
    """A new array: ``img`` with every fix applied; pixels outside the fixes' ROIs are untouched."""
    ensure_rgb_uint8(img)
    if isinstance(strength, bool) or not math.isfinite(strength) or not 0 <= strength <= 1:
        raise ValueError("correction strength must be a finite fraction between 0 and 1")
    result = img.copy()
    height, width = img.shape[:2]
    for fix in fixes:
        x0, y0, x1, y1 = fix.roi
        if x1 > width or y1 > height:
            raise ValueError(f"fix ROI {fix.roi} lies outside the {width}x{height} image")
        result[y0:y1, x0:x1] = _corrected_patch(result[y0:y1, x0:x1], fix.mask, strength)
    return result


def eligible_faces(img: np.ndarray, dpi: float, detector: FaceDetector | None) -> tuple[Face, ...]:
    """Faces that pass the score and physical-size gates, as used by auto red-eye."""
    if isinstance(dpi, bool) or not math.isfinite(dpi) or dpi <= 0:
        raise ValueError(f"dpi must be a positive finite number, got {dpi!r}")
    ensure_rgb_uint8(img)
    min_iod = _mm_to_px(MIN_INTEROCULAR_MM, dpi)
    return tuple(
        f
        for f in detect_faces_full_res(img, detector)
        if f.score >= MIN_FACE_SCORE and _interocular(f) >= min_iod
    )


def detect_fixes(
    img: np.ndarray, dpi: float, detector: FaceDetector | None = None
) -> tuple[EyeFix, ...]:
    """Pending pupil fixes with the same full-resolution and physical-size gates as auto."""
    return find_red_eyes(img, eligible_faces(img, dpi, detector))


def remove_red_eye(img: np.ndarray, dpi: int, detector: FaceDetector | None = None) -> np.ndarray:
    """``img`` with red pupils corrected, as a new array (an ``Enhancer``).

    ``img`` is an upright RGB uint8 array and is not modified. Faces whose eyes are closer than
    ``MIN_INTEROCULAR_MM`` at ``dpi`` are skipped.
    """
    faces = eligible_faces(img, dpi, detector)
    fixes = find_red_eyes(img, faces)
    logger.info("red-eye: corrected %d eye(s) in %d face(s)", len(fixes), len(faces))
    return apply_fixes(img, fixes)
