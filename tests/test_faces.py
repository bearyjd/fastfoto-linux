import dataclasses
import hashlib
from importlib import resources
from pathlib import Path

import numpy as np
import pytest

from fastfoto_linux.enhance.faces import (
    MODEL_FILENAME,
    MODEL_PACKAGE,
    MODEL_SHA256,
    Face,
    FaceDetector,
    default_detector,
    ensure_rgb_uint8,
)
from tests.face_images import load_astronaut, textured_photo_without_faces

MIN_UPRIGHT_SCORE = 0.9
LICENSE_FILENAME = "LICENSE-YuNet"


@pytest.fixture(scope="module")
def detector() -> FaceDetector:
    return FaceDetector()


@pytest.fixture
def model_copy(tmp_path: Path) -> Path:
    source = resources.files(MODEL_PACKAGE).joinpath(MODEL_FILENAME)
    target = tmp_path / MODEL_FILENAME
    target.write_bytes(source.read_bytes())
    return target


def test_model_and_licence_ship_as_package_data() -> None:
    models = resources.files(MODEL_PACKAGE)
    model = models.joinpath(MODEL_FILENAME)
    assert model.is_file()
    assert hashlib.sha256(model.read_bytes()).hexdigest() == MODEL_SHA256
    assert "MIT License" in models.joinpath(LICENSE_FILENAME).read_text()


def test_detects_the_upright_portrait(detector: FaceDetector) -> None:
    image = load_astronaut()
    faces = detector.detect(image)
    assert len(faces) == 1
    face = faces[0]
    assert face.score >= MIN_UPRIGHT_SCORE
    assert 0 <= face.x + face.width / 2 <= image.shape[1]
    assert 0 <= face.y + face.height / 2 <= image.shape[0]
    assert len(face.landmarks) == 5
    assert all(len(point) == 2 for point in face.landmarks)


def test_detection_does_not_mutate_a_read_only_input(detector: FaceDetector) -> None:
    image = load_astronaut()
    original = image.copy()
    image.setflags(write=False)
    detector.detect(image)
    assert np.array_equal(image, original)


def test_image_without_faces_gives_an_empty_tuple(detector: FaceDetector) -> None:
    assert detector.detect(textured_photo_without_faces(400, 500)) == ()


def test_score_threshold_filters_detections() -> None:
    strict = FaceDetector(score_threshold=0.99)
    assert strict.detect(load_astronaut()) == ()


@pytest.mark.parametrize("threshold", [0.0, -0.1, 1.5])
def test_score_threshold_must_be_a_probability(threshold: float) -> None:
    with pytest.raises(ValueError, match="score_threshold"):
        FaceDetector(score_threshold=threshold)


def test_face_is_frozen() -> None:
    face = Face(x=1.0, y=2.0, width=3.0, height=4.0, landmarks=((0.0, 0.0),), score=0.9)
    with pytest.raises(dataclasses.FrozenInstanceError):
        face.x = 5.0  # type: ignore[misc]


def test_missing_model_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="face model"):
        FaceDetector(model_path=tmp_path / "absent.onnx")


def test_corrupt_model_file_is_rejected(model_copy: Path) -> None:
    data = bytearray(model_copy.read_bytes())
    data[len(data) // 2] ^= 0xFF
    model_copy.write_bytes(bytes(data))
    with pytest.raises(ValueError, match="sha256"):
        FaceDetector(model_path=model_copy)


def test_truncated_model_file_is_rejected(model_copy: Path) -> None:
    model_copy.write_bytes(model_copy.read_bytes()[:1000])
    with pytest.raises(ValueError, match="sha256"):
        FaceDetector(model_path=model_copy)


def test_explicit_model_path_loads_the_same_model(model_copy: Path) -> None:
    faces = FaceDetector(model_path=model_copy).detect(load_astronaut())
    assert len(faces) == 1


def test_default_detector_is_created_once() -> None:
    assert default_detector() is default_detector()


@pytest.mark.parametrize(
    "bad",
    [
        np.zeros((10, 10), dtype=np.uint8),
        np.zeros((10, 10, 4), dtype=np.uint8),
        np.zeros((10, 10, 3), dtype=np.uint16),
        np.zeros((0, 10, 3), dtype=np.uint8),
    ],
    ids=["gray", "rgba", "uint16", "empty"],
)
def test_non_rgb_uint8_input_is_rejected(bad: np.ndarray, detector: FaceDetector) -> None:
    with pytest.raises(ValueError, match="RGB"):
        ensure_rgb_uint8(bad)
    with pytest.raises(ValueError, match="RGB"):
        detector.detect(bad)
