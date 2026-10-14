import dataclasses
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from importlib import metadata, resources
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
from tests.face_images import load_astronaut, photo_with_face, textured_photo_without_faces

MIN_UPRIGHT_SCORE = 0.9
THREADS = 8
CALLS_PER_THREAD = 10
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


def test_licence_file_ends_with_a_newline() -> None:
    licence = resources.files(MODEL_PACKAGE).joinpath(LICENSE_FILENAME).read_text()
    assert licence.endswith("\n")


def test_yunet_licence_is_listed_in_the_distribution_metadata() -> None:
    files = metadata.distribution("fastfoto-linux").files or []
    assert any(path.name == LICENSE_FILENAME for path in files)


def test_default_detector_sees_a_face_that_scores_below_the_orientation_floor() -> None:
    # The upside-down portrait scores about 0.78: found at the 0.7 detection threshold but weak
    # enough to count for nothing in orientation scoring (floor 0.8).
    upside_down = np.ascontiguousarray(np.rot90(load_astronaut(), 2))
    faces = default_detector().detect(upside_down)
    assert len(faces) == 1
    assert 0.7 <= faces[0].score < 0.8


@pytest.mark.parametrize("bad", [None, "photo.png", [[[0, 0, 0]]], b"abc"])
def test_non_array_input_is_a_type_error(bad: object, detector: FaceDetector) -> None:
    with pytest.raises(TypeError, match="numpy"):
        ensure_rgb_uint8(bad)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="numpy"):
        detector.detect(bad)  # type: ignore[arg-type]


def test_shared_default_detector_is_thread_safe() -> None:
    images = [
        load_astronaut(),
        photo_with_face(300, 400, 1, (20, 60)),
        photo_with_face(400, 300, 1, (100, 20)),
        photo_with_face(480, 640, 1, (100, 300)),
        photo_with_face(320, 512, 1, (30, 200)),
    ]
    expected = [default_detector().detect(image) for image in images]
    assert all(expected)
    start_together = threading.Barrier(THREADS)

    def work(offset: int) -> list[tuple[int, tuple[Face, ...]]]:
        start_together.wait()
        indices = [(offset + call) % len(images) for call in range(CALLS_PER_THREAD)]
        return [(index, default_detector().detect(images[index])) for index in indices]

    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        results = list(pool.map(work, range(THREADS)))
    assert all(faces == expected[index] for result in results for index, faces in result)
