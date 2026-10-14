"""Auto-upright photos by scoring face-detector confidence on the four right-angle rotations.

Faces are only found reliably when upright, so the rotation whose faces score clearly highest is
the right one. Photos without a clear winner (no faces, or faces that disagree) are left alone.
YuNet landmarks look upright even on rotated faces, so only detection confidence is used. Pixels
are rotated; the EXIF Orientation tag is neither read nor written.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass

import cv2
import numpy as np

from fastfoto_linux.enhance.faces import FaceDetector, default_detector, ensure_rgb_uint8

logger = logging.getLogger(__name__)

CANDIDATE_ROTATIONS = (0, 90, 180, 270)
# Detector working size in pixels (not a physical length): the decision does not depend on dpi.
WORKING_LONG_SIDE_PX = 1000
CONFIDENCE_FLOOR = 0.8
MIN_BEST_SCORE = 0.1
MIN_RUNNER_UP_RATIO = 1.5

_CV2_ROTATION_CODE = {
    90: cv2.ROTATE_90_CLOCKWISE,
    180: cv2.ROTATE_180,
    270: cv2.ROTATE_90_COUNTERCLOCKWISE,
}


@dataclass(frozen=True)
class OrientationDecision:
    """``rotation`` is the clockwise angle to apply; ``scores`` follow ``CANDIDATE_ROTATIONS``.

    ``confident`` is False when no rotation won clearly; ``rotation`` is then 0 (leave as is).
    """

    rotation: int
    scores: tuple[float, ...]
    confident: bool


def _choose_rotation(scores: Sequence[float]) -> int | None:
    """The winning rotation, or ``None`` if the best score is too low or too close to second."""
    ranked = sorted(scores, reverse=True)
    best, runner_up = ranked[0], ranked[1]
    if best < MIN_BEST_SCORE or best < MIN_RUNNER_UP_RATIO * runner_up:
        return None
    return CANDIDATE_ROTATIONS[list(scores).index(best)]


def apply_rotation(img: np.ndarray, rotation: int) -> np.ndarray:
    """A new array holding ``img`` rotated clockwise by ``rotation`` degrees; ``img`` is intact."""
    if rotation not in CANDIDATE_ROTATIONS:
        raise ValueError(f"rotation must be one of {CANDIDATE_ROTATIONS}, got {rotation}")
    if rotation == 0:
        return img.copy()
    return cv2.rotate(img, _CV2_ROTATION_CODE[rotation])


def _working_copy(img: np.ndarray) -> np.ndarray:
    scale = WORKING_LONG_SIDE_PX / max(img.shape[:2])
    interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
    return cv2.resize(img, None, fx=scale, fy=scale, interpolation=interpolation)


def _rotation_score(detector: FaceDetector, working: np.ndarray, rotation: int) -> float:
    faces = detector.detect(apply_rotation(working, rotation))
    return float(sum(max(0.0, face.score - CONFIDENCE_FLOOR) for face in faces))


def decide_orientation(
    img: np.ndarray, dpi: int, detector: FaceDetector | None = None
) -> OrientationDecision:
    """Decide which clockwise rotation makes the faces in ``img`` upright, if any.

    ``img`` is an RGB uint8 array and is not modified. ``dpi`` must be positive; the working
    scale is fixed in pixels so the decision does not depend on it.
    """
    if dpi <= 0:
        raise ValueError(f"dpi must be positive, got {dpi}")
    ensure_rgb_uint8(img)
    active = default_detector() if detector is None else detector
    working = _working_copy(img)
    scores = tuple(_rotation_score(active, working, r) for r in CANDIDATE_ROTATIONS)
    chosen = _choose_rotation(scores)
    logger.debug("orientation scores %s -> %s", scores, chosen)
    return OrientationDecision(
        rotation=0 if chosen is None else chosen,
        scores=scores,
        confident=chosen is not None,
    )


def auto_orient(img: np.ndarray, dpi: int, detector: FaceDetector | None = None) -> np.ndarray:
    """``img`` turned upright when faces say how; otherwise an unchanged copy. Never mutates."""
    decision = decide_orientation(img, dpi, detector)
    return apply_rotation(img, decision.rotation)
