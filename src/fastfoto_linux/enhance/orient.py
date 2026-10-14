"""Auto-upright photos by scoring face-detector confidence on the four right-angle rotations."""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from fastfoto_linux.enhance.faces import FaceDetector

CANDIDATE_ROTATIONS = (0, 90, 180, 270)
WORKING_LONG_SIDE_PX = 1000
CONFIDENCE_FLOOR = 0.8
MIN_BEST_SCORE = 0.1
MIN_RUNNER_UP_RATIO = 1.5


@dataclass(frozen=True)
class OrientationDecision:
    """``rotation`` is the clockwise angle to apply; ``scores`` follow ``CANDIDATE_ROTATIONS``."""

    rotation: int
    scores: tuple[float, float, float, float]
    confident: bool


def _choose_rotation(scores: Sequence[float]) -> int | None:
    raise NotImplementedError


def apply_rotation(img: np.ndarray, rotation: int) -> np.ndarray:
    raise NotImplementedError


def decide_orientation(
    img: np.ndarray, dpi: int, detector: FaceDetector | None = None
) -> OrientationDecision:
    raise NotImplementedError


def auto_orient(img: np.ndarray, dpi: int, detector: FaceDetector | None = None) -> np.ndarray:
    raise NotImplementedError
