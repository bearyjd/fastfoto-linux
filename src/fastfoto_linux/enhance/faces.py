"""YuNet face detection (OpenCV ``FaceDetectorYN``) with an integrity-checked vendored model."""

from dataclasses import dataclass
from pathlib import Path

import numpy as np

MODEL_PACKAGE = "fastfoto_linux.models"
MODEL_FILENAME = "face_detection_yunet_2023mar.onnx"
MODEL_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
DEFAULT_SCORE_THRESHOLD = 0.7


@dataclass(frozen=True)
class Face:
    """One detected face; coordinates are pixels in the image that was passed to ``detect``.

    ``landmarks`` are (x, y) points: right eye, left eye, nose tip, right and left mouth corner.
    """

    x: float
    y: float
    width: float
    height: float
    landmarks: tuple[tuple[float, float], ...]
    score: float


class FaceDetector:
    def __init__(
        self,
        model_path: Path | None = None,
        score_threshold: float = DEFAULT_SCORE_THRESHOLD,
    ) -> None:
        raise NotImplementedError

    def detect(self, img_rgb: np.ndarray) -> tuple[Face, ...]:
        raise NotImplementedError


def ensure_rgb_uint8(img: np.ndarray) -> None:
    raise NotImplementedError


def default_detector() -> FaceDetector:
    raise NotImplementedError
