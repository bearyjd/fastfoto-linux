"""YuNet face detection (OpenCV ``FaceDetectorYN``) with an integrity-checked vendored model.

The ONNX model ships as package data (``fastfoto_linux/models``); its sha256 is verified on every
load and it is never downloaded. OpenCV's detector keeps per-call state (the input size), so each
``FaceDetector`` serialises its own calls with a lock: one instance, including the shared
``default_detector()``, is safe to use from several threads, though they then take turns.
"""

import hashlib
import threading
from dataclasses import dataclass
from functools import cache
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

import cv2
import numpy as np

from fastfoto_linux.imaging import ensure_rgb_uint8

MODEL_PACKAGE = "fastfoto_linux.models"
MODEL_FILENAME = "face_detection_yunet_2023mar.onnx"
MODEL_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
DEFAULT_SCORE_THRESHOLD = 0.7
NMS_THRESHOLD = 0.3
TOP_K = 5000
INITIAL_INPUT_SIZE = (320, 320)

_DEFAULT_DETECTOR_LOCK = threading.Lock()

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
        self._lock = threading.Lock()

    def detect(self, img_rgb: np.ndarray) -> tuple[Face, ...]:
        """Return every face scoring at least the threshold, in ``img_rgb`` pixel coordinates."""
        ensure_rgb_uint8(img_rgb)
        height, width = img_rgb.shape[:2]
        bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
        with self._lock:
            self._net.setInputSize((width, height))
            _, rows = self._net.detect(bgr)
        return () if rows is None else tuple(_face_from_row(row) for row in rows)


@cache
def _create_default_detector() -> FaceDetector:
    return FaceDetector()


def default_detector() -> FaceDetector:
    """The shared detector over the vendored model, created once on first use (thread-safe)."""
    with _DEFAULT_DETECTOR_LOCK:
        return _create_default_detector()
