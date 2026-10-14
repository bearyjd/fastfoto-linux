"""detect_faces_full_res with a stub detector: what it is fed and how results map back."""

import dataclasses
from collections.abc import Callable
from typing import cast

import numpy as np
import pytest

from fastfoto_linux.enhance.faces import Face, FaceDetector
from fastfoto_linux.enhance.redeye import detect_faces_full_res

MAX_INPUT_LONG_SIDE = 1000
EYES = slice(0, 2)
COARSE_SCORE = 0.95
REFINED_SCORE = 0.97
TOLERANCE = 1e-6
Responder = Callable[[int, np.ndarray], tuple[Face, ...]]


class StubDetector:
    """Records the shape of every image it is given and answers from ``respond``."""

    def __init__(self, respond: Responder) -> None:
        self.shapes: list[tuple[int, ...]] = []
        self.crops: list[tuple[int, int, int, int]] = []  # left, top, right, bottom of each crop
        self._respond = respond

    def detect(self, img_rgb: np.ndarray) -> tuple[Face, ...]:
        self.shapes.append(img_rgb.shape)
        return self._respond(len(self.shapes) - 1, img_rgb)


def _face(
    left: tuple[float, float], right: tuple[float, float], box: tuple[float, ...], score: float
) -> Face:
    nose = ((left[0] + right[0]) / 2, left[1] + 30.0)
    mouth = (nose[0] - 10.0, nose[1] + 20.0), (nose[0] + 10.0, nose[1] + 20.0)
    return Face(*box, landmarks=(left, right, nose, *mouth), score=score)  # type: ignore[arg-type]


def _as_detector(stub: StubDetector) -> FaceDetector:
    return cast(FaceDetector, stub)


def _coded_image(height: int, width: int) -> np.ndarray:
    """Every pixel encodes its own (x, y), so a crop reveals where it was cut from."""
    cols, rows = np.arange(width), np.arange(height)
    img = np.zeros((height, width, 3), dtype=np.uint8)
    img[..., 0] = (cols % 256)[np.newaxis, :]
    img[..., 1] = (cols // 256)[np.newaxis, :] + 8 * (rows // 256)[:, np.newaxis]
    img[..., 2] = (rows % 256)[:, np.newaxis]
    return img


def _crop_origin(crop: np.ndarray) -> tuple[int, int]:
    red, green, blue = (int(v) for v in crop[0, 0])
    return red + 256 * (green % 8), blue + 256 * (green // 8)


def _shifted(face: Face, dx: float, dy: float) -> Face:
    return Face(
        x=face.x + dx,
        y=face.y + dy,
        width=face.width,
        height=face.height,
        landmarks=tuple((x + dx, y + dy) for x, y in face.landmarks),
        score=face.score,
    )


def test_downscaled_detection_maps_back_with_half_pixel_centres() -> None:
    height, width = 2000, 3000
    coarse = _face((400.0, 300.0), (460.0, 304.0), (380.0, 270.0, 100.0, 120.0), COARSE_SCORE)
    stub = StubDetector(lambda call, _img: (coarse,) if call == 0 else ())
    faces = detect_faces_full_res(np.zeros((height, width, 3), np.uint8), _as_detector(stub))
    small_width, small_height = 1000, 667
    scale_x, scale_y = width / small_width, height / small_height
    assert stub.shapes[0] == (small_height, small_width, 3)
    assert all(max(shape[:2]) <= MAX_INPUT_LONG_SIDE for shape in stub.shapes)
    assert len(faces) == 1
    for want, got in zip(coarse.landmarks[EYES], faces[0].landmarks[EYES], strict=True):
        assert got[0] == pytest.approx((want[0] + 0.5) * scale_x - 0.5, abs=TOLERANCE)
        assert got[1] == pytest.approx((want[1] + 0.5) * scale_y - 0.5, abs=TOLERANCE)
    assert faces[0].x == pytest.approx((coarse.x + 0.5) * scale_x - 0.5, abs=TOLERANCE)
    assert faces[0].y == pytest.approx((coarse.y + 0.5) * scale_y - 0.5, abs=TOLERANCE)
    assert faces[0].width == pytest.approx(coarse.width * scale_x, abs=TOLERANCE)
    assert faces[0].height == pytest.approx(coarse.height * scale_y, abs=TOLERANCE)
    assert faces[0].score == COARSE_SCORE


def test_a_photo_within_the_working_size_is_detected_in_one_pass() -> None:
    face = _face((300.0, 200.0), (360.0, 204.0), (280.0, 170.0, 100.0, 120.0), COARSE_SCORE)
    stub = StubDetector(lambda _call, _img: (face,))
    faces = detect_faces_full_res(np.zeros((600, 800, 3), np.uint8), _as_detector(stub))
    assert stub.shapes == [(600, 800, 3)]
    assert faces == (face,)


def _refining_stub(coarse: Face, refined_full_res: tuple[Face, ...]) -> StubDetector:
    """Answers the whole-image call with ``coarse``; a crop gets the faces it fully contains."""

    def respond(call: int, img: np.ndarray) -> tuple[Face, ...]:
        if call == 0:
            return (coarse,)
        left, top = _crop_origin(img)
        height, width = img.shape[:2]
        stub.crops.append((left, top, left + width, top + height))
        return tuple(
            _shifted(face, -left, -top)
            for face in refined_full_res
            if face.x >= left
            and face.y >= top
            and face.x + face.width <= left + width
            and face.y + face.height <= top + height
        )

    stub = StubDetector(respond)
    return stub


def test_a_face_is_redetected_on_a_full_resolution_crop() -> None:
    coarse = _face((460.0, 400.0), (500.0, 402.0), (440.0, 370.0, 90.0, 100.0), COARSE_SCORE)
    truth = _face((692.25, 601.5), (751.75, 604.0), (660.0, 560.0, 140.0, 150.0), REFINED_SCORE)
    stub = _refining_stub(coarse, (truth,))
    faces = detect_faces_full_res(_coded_image(1200, 1500), _as_detector(stub))
    assert len(faces) == 1
    for want, got in zip(truth.landmarks[EYES], faces[0].landmarks[EYES], strict=True):
        assert got == pytest.approx(want, abs=TOLERANCE)
    assert faces[0].score == REFINED_SCORE
    assert all(max(shape[:2]) <= MAX_INPUT_LONG_SIDE for shape in stub.shapes)
    assert stub.shapes[1][0] < 1200 and stub.shapes[1][1] < 1500


def test_the_redetected_face_nearest_the_original_is_chosen() -> None:
    coarse = _face((460.0, 400.0), (500.0, 402.0), (440.0, 370.0, 90.0, 100.0), COARSE_SCORE)
    truth = _face((692.25, 601.5), (751.75, 604.0), (660.0, 560.0, 140.0, 150.0), REFINED_SCORE)
    neighbour = _shifted(truth, 20.0, 0.0)  # also inside the original box, but further out
    stub = _refining_stub(coarse, (neighbour, truth))
    faces = detect_faces_full_res(_coded_image(1200, 1500), _as_detector(stub))
    assert faces[0].landmarks[0] == pytest.approx(truth.landmarks[0], abs=TOLERANCE)


def test_a_crop_without_a_matching_face_keeps_the_coarse_one() -> None:
    coarse = _face((460.0, 400.0), (500.0, 402.0), (440.0, 370.0, 90.0, 100.0), COARSE_SCORE)
    elsewhere = _face((100.0, 100.0), (140.0, 100.0), (80.0, 70.0, 90.0, 100.0), REFINED_SCORE)
    beside = _face((812.0, 610.0), (832.0, 612.0), (800.0, 600.0, 60.0, 70.0), REFINED_SCORE)
    for answers in ((), (elsewhere,), (beside,)):
        stub = _refining_stub(coarse, answers)
        faces = detect_faces_full_res(_coded_image(1200, 1500), _as_detector(stub))
        assert len(faces) == 1
        assert faces[0].score == COARSE_SCORE
        assert faces[0].landmarks[0][0] == pytest.approx((460.0 + 0.5) * 1.5 - 0.5, abs=TOLERANCE)


def test_a_face_filling_the_photo_is_redetected_on_a_crop_within_the_working_size() -> None:
    coarse = _face((300.0, 300.0), (500.0, 300.0), (150.0, 100.0, 500.0, 600.0), COARSE_SCORE)
    stub = StubDetector(lambda call, _img: (coarse,) if call == 0 else ())
    detect_faces_full_res(np.zeros((2400, 3000, 3), np.uint8), _as_detector(stub))
    assert len(stub.shapes) == 2
    assert all(max(shape[:2]) <= MAX_INPUT_LONG_SIDE for shape in stub.shapes)


def test_a_face_outside_the_photo_is_not_redetected() -> None:
    stray = _face((5000.0, 400.0), (5040.0, 402.0), (4980.0, 370.0, 90.0, 100.0), COARSE_SCORE)
    stub = StubDetector(lambda call, _img: (stray,) if call == 0 else ())
    faces = detect_faces_full_res(np.zeros((1200, 1500, 3), np.uint8), _as_detector(stub))
    assert len(stub.shapes) == 1
    assert faces[0].score == COARSE_SCORE


def _truth(coarse: Face, scale: float, offset: float) -> Face:
    """``coarse`` mapped to full resolution (pixel centres, same scale both ways), then nudged."""
    return _shifted(
        Face(
            x=(coarse.x + 0.5) * scale - 0.5,
            y=(coarse.y + 0.5) * scale - 0.5,
            width=coarse.width * scale,
            height=coarse.height * scale,
            landmarks=tuple(
                ((x + 0.5) * scale - 0.5, (y + 0.5) * scale - 0.5) for x, y in coarse.landmarks
            ),
            score=REFINED_SCORE,
        ),
        offset,
        offset,
    )


# Faces whose crops are clipped by the left, top, right or bottom edge of a 1200 x 1500 photo
# (shrunk by 1.5 for the first pass): (eye, eye, box) in shrunk coordinates, crop edge, its value.
EDGE_FACES = {
    "left": (((30.0, 400.0), (70.0, 402.0), (10.0, 370.0, 80.0, 100.0)), 0, 0),
    "top": (((460.0, 40.0), (500.0, 42.0), (440.0, 10.0, 90.0, 100.0)), 1, 0),
    "right": (((900.0, 400.0), (940.0, 402.0), (880.0, 370.0, 90.0, 100.0)), 2, 1500),
    "bottom": (((460.0, 720.0), (500.0, 722.0), (440.0, 690.0, 90.0, 100.0)), 3, 1200),
}


@pytest.mark.parametrize(("placement", "side", "edge"), EDGE_FACES.values(), ids=EDGE_FACES.keys())
def test_crops_are_clipped_to_the_photo_on_every_side(
    placement: tuple[tuple[float, float], tuple[float, float], tuple[float, ...]],
    side: int,
    edge: int,
) -> None:
    left_eye, right_eye, box = placement
    coarse = _face(left_eye, right_eye, box, COARSE_SCORE)
    truth = _truth(coarse, 1.5, 2.0)
    stub = _refining_stub(coarse, (truth,))
    faces = detect_faces_full_res(_coded_image(1200, 1500), _as_detector(stub))
    assert len(stub.crops) == 1
    assert stub.crops[0][side] == edge
    assert faces[0].score == REFINED_SCORE
    for want, got in zip(truth.landmarks[EYES], faces[0].landmarks[EYES], strict=True):
        assert got == pytest.approx(want, abs=TOLERANCE)


def _two_coarse_faces_stub(first: Face, second: Face, answers: tuple[Face, Face]) -> StubDetector:
    def respond(call: int, img: np.ndarray) -> tuple[Face, ...]:
        if call == 0:
            return (first, second)
        left, top = _crop_origin(img)
        return (_shifted(answers[call - 1], -left, -top),)

    return StubDetector(respond)


def test_overlapping_coarse_boxes_over_one_face_give_it_once() -> None:
    first = _face((460.0, 400.0), (500.0, 402.0), (440.0, 370.0, 90.0, 100.0), COARSE_SCORE)
    second = _face((462.0, 401.0), (502.0, 403.0), (442.0, 371.0, 90.0, 100.0), COARSE_SCORE)
    truth = _face((692.25, 601.5), (751.75, 604.0), (660.0, 560.0, 140.0, 150.0), REFINED_SCORE)
    surer = dataclasses.replace(truth, score=0.99)
    for answers in ((truth, surer), (surer, truth)):
        stub = _two_coarse_faces_stub(first, second, answers)
        faces = detect_faces_full_res(_coded_image(1200, 1500), _as_detector(stub))
        assert len(faces) == 1
        assert faces[0].score == 0.99


def test_distinct_faces_are_both_kept() -> None:
    first = _face((460.0, 400.0), (500.0, 402.0), (440.0, 370.0, 90.0, 100.0), COARSE_SCORE)
    other = _face((200.0, 300.0), (240.0, 302.0), (180.0, 270.0, 90.0, 100.0), COARSE_SCORE)
    truths = (_truth(first, 1.5, 1.0), _truth(other, 1.5, 1.0))
    faces = detect_faces_full_res(
        _coded_image(1200, 1500), _as_detector(_two_coarse_faces_stub(first, other, truths))
    )
    assert [face.landmarks[0] for face in faces] == [t.landmarks[0] for t in truths]
