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

from fastfoto_linux.enhance.faces import Face, FaceDetector, default_detector, ensure_rgb_uint8

logger = logging.getLogger(__name__)

MM_PER_INCH = 25.4
# Detector working size in pixels (not a physical length): faces are found on this copy.
DETECT_LONG_SIDE_PX = 1000
MIN_FACE_SCORE = 0.8
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
MAX_ASPECT_RATIO = 2.0
MIN_FILL_RATIO = 0.4
MIN_RING_CONTRAST = 20
RING_INNER_FRACTION = 0.5
RING_OUTER_FRACTION = 2.0
# Pupils are small and round: grow the mask and feather it in proportion to the pupil radius.
GROW_FRACTION = 0.25
FEATHER_FRACTION = 0.3
MIN_FEATHER_SIGMA_PX = 0.5
# Pixels with both G and B at least this bright are specular highlights and stay as they are.
HIGHLIGHT_MIN_LEVEL = 200
DARKEN = 0.9
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


def _mm_to_px(mm: float, dpi: int) -> float:
    return mm * dpi / MM_PER_INCH


def _interocular(face: Face) -> float:
    (x0, y0), (x1, y1) = face.landmarks[:LANDMARKS_PER_FACE]
    return math.hypot(x1 - x0, y1 - y0)


def _scale_face(face: Face, scale_x: float, scale_y: float) -> Face:
    return Face(
        x=face.x * scale_x,
        y=face.y * scale_y,
        width=face.width * scale_x,
        height=face.height * scale_y,
        landmarks=tuple((x * scale_x, y * scale_y) for x, y in face.landmarks),
        score=face.score,
    )


def detect_faces_full_res(
    img: np.ndarray, detector: FaceDetector | None = None
) -> tuple[Face, ...]:
    """Faces found on a downscaled copy of ``img``, mapped back to ``img`` pixel coordinates."""
    ensure_rgb_uint8(img)
    active = default_detector() if detector is None else detector
    height, width = img.shape[:2]
    long_side = max(height, width)
    if long_side <= DETECT_LONG_SIDE_PX:
        return active.detect(img)
    scale = DETECT_LONG_SIDE_PX / long_side
    size = (max(1, round(width * scale)), max(1, round(height * scale)))
    small = cv2.resize(img, size, interpolation=cv2.INTER_AREA)
    scale_x, scale_y = width / size[0], height / size[1]
    return tuple(_scale_face(face, scale_x, scale_y) for face in active.detect(small))


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
    """True if the blob's bounding box is close to square and well filled (a disc fills ~0.79)."""
    ys, xs = np.nonzero(component)
    width, height = int(xs.max() - xs.min()) + 1, int(ys.max() - ys.min()) + 1
    aspect = max(width, height) / min(width, height)
    return aspect <= MAX_ASPECT_RATIO and int(ys.size) / (width * height) >= MIN_FILL_RATIO


def _redness(patch: np.ndarray) -> np.ndarray:
    levels = patch.astype(np.int16)
    return levels[..., 0] - np.maximum(levels[..., 1], levels[..., 2])


def _ring_contrast(patch: np.ndarray, component: np.ndarray) -> float | None:
    """Mean redness of the blob minus the median redness of the ring around it (None: no ring)."""
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
        return None
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
    contrast = _ring_contrast(patch, component)
    if contrast is None or contrast < MIN_RING_CONTRAST:
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
    grow = max(1, round(GROW_FRACTION * radius))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * grow + 1, 2 * grow + 1))
    grown = cv2.dilate(mask.astype(np.uint8), kernel).astype(np.float32)
    sigma = max(MIN_FEATHER_SIGMA_PX, FEATHER_FRACTION * radius)
    alpha = np.clip(cv2.GaussianBlur(grown, (0, 0), sigma), 0.0, 1.0)
    highlight = patch[..., 1:].min(axis=2) >= HIGHLIGHT_MIN_LEVEL
    alpha[highlight] = 0.0
    return alpha


def _corrected_patch(patch: np.ndarray, mask: np.ndarray) -> np.ndarray:
    source = patch.astype(np.float32)
    neutral = (source[..., 1] + source[..., 2]) / 2
    fixed = np.repeat(np.minimum(source[..., 0], neutral)[..., np.newaxis], 3, axis=2) * DARKEN
    alpha = _feathered_alpha(patch, mask)[..., np.newaxis]
    blended = source + alpha * (fixed - source)
    return np.clip(np.rint(blended), 0, MAX_LEVEL).astype(np.uint8)


def apply_fixes(img: np.ndarray, fixes: Sequence[EyeFix]) -> np.ndarray:
    """A new array: ``img`` with every fix applied; pixels outside the fixes' ROIs are untouched."""
    ensure_rgb_uint8(img)
    result = img.copy()
    for fix in fixes:
        x0, y0, x1, y1 = fix.roi
        result[y0:y1, x0:x1] = _corrected_patch(result[y0:y1, x0:x1], fix.mask)
    return result


def remove_red_eye(img: np.ndarray, dpi: int, detector: FaceDetector | None = None) -> np.ndarray:
    """``img`` with red pupils corrected, as a new array (an ``Enhancer``).

    ``img`` is an upright RGB uint8 array and is not modified. Faces whose eyes are closer than
    ``MIN_INTEROCULAR_MM`` at ``dpi`` are skipped.
    """
    if dpi <= 0:
        raise ValueError(f"dpi must be positive, got {dpi}")
    ensure_rgb_uint8(img)
    min_iod = _mm_to_px(MIN_INTEROCULAR_MM, dpi)
    faces = tuple(f for f in detect_faces_full_res(img, detector) if _interocular(f) >= min_iod)
    fixes = find_red_eyes(img, faces)
    logger.info("red-eye: corrected %d eye(s) in %d face(s)", len(fixes), len(faces))
    return apply_fixes(img, fixes)
