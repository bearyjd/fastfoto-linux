"""YuNet face detection (OpenCV ``FaceDetectorYN``) with an integrity-checked vendored model.

The ONNX model ships as package data (``fastfoto_linux/models``); its sha256 is verified on every
load and it is never downloaded. Detector instances keep OpenCV state between calls, so share one
per thread rather than across threads.
"""

import hashlib
from dataclasses import dataclass
from functools import cache
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

import cv2
import numpy as np

MODEL_PACKAGE = "fastfoto_linux.models"
MODEL_FILENAME = "face_detection_yunet_2023mar.onnx"
MODEL_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
DEFAULT_SCORE_THRESHOLD = 0.7
NMS_THRESHOLD = 0.3
TOP_K = 5000
INITIAL_INPUT_SIZE = (320, 320)
RGB_NDIM = 3
RGB_CHANNELS = 3

# One YuNet row: x, y, w, h, five (x, y) landmarks, score.
_BOX = slice(0, 4)
_LANDMARKS = slice(4, 14)
_SCORE = 14


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


def ensure_rgb_uint8(img: np.ndarray) -> None:
    """Raise ``ValueError`` unless ``img`` is a non-empty height x width x 3 uint8 array."""
    if (
        img.ndim != RGB_NDIM
        or img.shape[2] != RGB_CHANNELS
        or img.dtype != np.uint8
        or img.size == 0
    ):
        raise ValueError(
            f"expected a non-empty RGB uint8 image (H x W x 3), got shape {img.shape} "
            f"dtype {img.dtype}"
        )


def _read_verified_model(model_path: Path | None) -> bytes:
    source: Traversable = (
        resources.files(MODEL_PACKAGE).joinpath(MODEL_FILENAME)
        if model_path is None
        else model_path
    )
    try:
        data = source.read_bytes()
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"YuNet face model not found: {source}") from exc
    digest = hashlib.sha256(data).hexdigest()
    if digest != MODEL_SHA256:
        raise ValueError(
            f"YuNet face model {source} is corrupt or not the vendored model: "
            f"sha256 {digest}, expected {MODEL_SHA256}"
        )
    return data


def _face_from_row(row: np.ndarray) -> Face:
    x, y, width, height = (float(v) for v in row[_BOX])
    points = row[_LANDMARKS].reshape(-1, 2)
    return Face(
        x=x,
        y=y,
        width=width,
        height=height,
        landmarks=tuple((float(px), float(py)) for px, py in points),
        score=float(row[_SCORE]),
    )


class FaceDetector:
    """Detect frontal faces in RGB images with the vendored YuNet model."""

    def __init__(
        self,
        model_path: Path | None = None,
        score_threshold: float = DEFAULT_SCORE_THRESHOLD,
    ) -> None:
        """Load the model (the vendored one unless ``model_path`` is given) and verify its sha256.

        Raises ``FileNotFoundError`` if the file is missing and ``ValueError`` if its checksum
        differs from ``MODEL_SHA256`` or ``score_threshold`` is not in (0, 1].
        """
        if not 0.0 < score_threshold <= 1.0:
            raise ValueError(f"score_threshold must be in (0, 1], got {score_threshold}")
        model = np.frombuffer(_read_verified_model(model_path), dtype=np.uint8)
        self._net = cv2.FaceDetectorYN.create(
            "onnx",
            model,
            np.empty(0, dtype=np.uint8),
            INITIAL_INPUT_SIZE,
            score_threshold,
            NMS_THRESHOLD,
            TOP_K,
        )

    def detect(self, img_rgb: np.ndarray) -> tuple[Face, ...]:
        """Return every face scoring at least the threshold, in ``img_rgb`` pixel coordinates."""
        ensure_rgb_uint8(img_rgb)
        height, width = img_rgb.shape[:2]
        bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
        self._net.setInputSize((width, height))
        _, rows = self._net.detect(bgr)
        return () if rows is None else tuple(_face_from_row(row) for row in rows)


@cache
def default_detector() -> FaceDetector:
    """The shared detector over the vendored model, created on first use."""
    return FaceDetector()
