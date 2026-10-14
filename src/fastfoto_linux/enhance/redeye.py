"""Red-eye removal on the enhanced copy of a photo (stub: implementation follows)."""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from fastfoto_linux.enhance.faces import Face, FaceDetector

MM_PER_INCH = 25.4
DETECT_LONG_SIDE_PX = 1000
MIN_FACE_SCORE = 0.8
MIN_INTEROCULAR_MM = 2.0
ROI_HALF_FRACTION = 0.25
LANDMARK_DISC_FRACTION = 0.1
MIN_REDNESS = 50
MIN_RED_LEVEL = 90
RED_DOMINANCE = 1.5
MIN_AREA_FRACTION = 0.01
MIN_COMPONENT_PIXELS = 4
MAX_AREA_FRACTION = 0.35
HIGHLIGHT_MIN_LEVEL = 200
DARKEN = 0.9


@dataclass(frozen=True, eq=False)
class EyeFix:
    """One red pupil to correct.

    ``roi`` is (x0, y0, x1, y1) in image pixels, x1/y1 exclusive; ``mask`` is a read-only
    boolean array of the ROI's shape marking the red component; ``center`` is the eye landmark.
    """

    roi: tuple[int, int, int, int]
    mask: np.ndarray
    center: tuple[float, float]


def detect_faces_full_res(
    img: np.ndarray, detector: FaceDetector | None = None
) -> tuple[Face, ...]:
    """Faces found on a downscaled copy of ``img``, mapped back to ``img`` pixel coordinates."""
    raise NotImplementedError


def find_red_eyes(img: np.ndarray, faces: Sequence[Face]) -> tuple[EyeFix, ...]:
    """The red pupils in ``img`` for ``faces`` (given in ``img`` pixel coordinates)."""
    raise NotImplementedError


def apply_fixes(img: np.ndarray, fixes: Sequence[EyeFix]) -> np.ndarray:
    """A new array: ``img`` with every fix applied; pixels outside the fixes' ROIs are untouched."""
    raise NotImplementedError


def remove_red_eye(img: np.ndarray, dpi: int, detector: FaceDetector | None = None) -> np.ndarray:
    """``img`` with red pupils corrected, as a new array (an ``Enhancer``)."""
    raise NotImplementedError
