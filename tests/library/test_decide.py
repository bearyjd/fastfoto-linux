"""Deciding a file's further quarter turn from its faces, on a portrait with a known answer."""

import hashlib
import os
from pathlib import Path

import pytest

from fastfoto_linux.enhance.faces import FaceDetector
from fastfoto_linux.enhance.orient import WORKING_LONG_SIDE_PX
from fastfoto_linux.library.decide import (
    decide_file,
    decide_files,
    load_working_image,
)
from fastfoto_linux.library.jpeg_exif import set_orientation
from fastfoto_linux.library.plan import Action
from tests.face_images import load_astronaut, photo_with_face, textured_photo_without_faces
from tests.library.jpeg_helpers import (
    APP1,
    EXIF_HEADER,
    make_jpeg,
    oversized_exif,
    rotate_cw,
    segment,
    sideways_jpeg,
    stored_pixels,
    upright_tag,
    write_file,
)

DEVIATIONS = (0, 90, 180, 270)
OLD_TAGS = (None, 1, 3, 6, 8)
FRONT = "2001/holiday_0001_a.jpg"


@pytest.fixture(scope="module")
def detector() -> FaceDetector:
    return FaceDetector()


def decided(tmp_path: Path, detector: FaceDetector, data: bytes, name: str = FRONT):
    write_file(tmp_path, name, data)
    return decide_file(tmp_path, name, detector)


# --- the known-answer matrix -------------------------------------------------------------------


@pytest.mark.parametrize("old_tag", OLD_TAGS)
@pytest.mark.parametrize("deviation", DEVIATIONS)
def test_the_proposed_turn_makes_the_portrait_upright(
    tmp_path: Path, detector: FaceDetector, deviation: int, old_tag: int | None
) -> None:
    data = sideways_jpeg(deviation, old_tag)
    row = decided(tmp_path, detector, data)
    assert row.path == FRONT
    assert row.old_tag == (old_tag or 1)
    assert row.size == len(data)
    assert row.mtime_ns == (tmp_path / FRONT).stat().st_mtime_ns
    if deviation == 0:
        assert (row.action, row.rotate_cw, row.reason) == (Action.KEEP, 0, "upright")
        assert row.new_tag is None
        assert row.sha256 == ""
        return
    assert row.action is Action.ROTATE
    assert row.rotate_cw == (360 - deviation) % 360
    assert row.new_tag == upright_tag(data)
    assert row.sha256 == hashlib.sha256(data).hexdigest()
    assert row.score > 0


@pytest.mark.parametrize("old_tag", [None, 6])
@pytest.mark.parametrize("deviation", [90, 270])
def test_a_fixed_file_is_kept_by_a_second_check(
    tmp_path: Path, detector: FaceDetector, deviation: int, old_tag: int | None
) -> None:
    first = decided(tmp_path, detector, sideways_jpeg(deviation, old_tag))
    assert first.action is Action.ROTATE and first.new_tag is not None
    fixed = set_orientation((tmp_path / FRONT).read_bytes(), first.new_tag)
    second = decided(tmp_path, detector, fixed, "fixed/again.jpg")
    assert (second.action, second.reason, second.rotate_cw) == (Action.KEEP, "upright", 0)
    assert second.old_tag == first.new_tag


# --- no clear answer, unsupported tags, backs, bad files ------------------------------


def test_a_photo_without_faces_is_kept_as_undecided(tmp_path: Path, detector: FaceDetector) -> None:
    data = make_jpeg(textured_photo_without_faces(300, 400))
    row = decided(tmp_path, detector, data)
    assert (row.action, row.reason, row.rotate_cw, row.score) == (Action.KEEP, "undecided", 0, 0.0)


@pytest.mark.parametrize("tag", [2, 4, 5, 7])
def test_mirrored_tags_are_skipped(tmp_path: Path, detector: FaceDetector, tag: int) -> None:
    row = decided(tmp_path, detector, sideways_jpeg(90, tag))
    assert (row.action, row.reason, row.old_tag, row.new_tag) == (
        Action.SKIP,
        "mirrored-tag",
        tag,
        None,
    )
    assert row.sha256 == ""


def test_a_tag_that_is_not_an_orientation_is_skipped(
    tmp_path: Path, detector: FaceDetector
) -> None:
    row = decided(tmp_path, detector, sideways_jpeg(90, 9))
    assert (row.action, row.reason) == (Action.SKIP, "invalid-tag")


def test_a_back_is_never_rotated(tmp_path: Path, detector: FaceDetector) -> None:
    data = make_jpeg(textured_photo_without_faces(300, 400))
    row = decided(tmp_path, detector, data, "x/holiday_0001_b.jpg")
    assert (row.action, row.reason, row.rotate_cw) == (Action.SKIP, "back", 0)


def test_a_back_that_shows_a_face_is_reported_as_looking_like_a_front(
    tmp_path: Path, detector: FaceDetector
) -> None:
    row = decided(tmp_path, detector, sideways_jpeg(90, None), "holiday_0002_B.JPG")
    assert (row.action, row.reason, row.rotate_cw) == (Action.SKIP, "back-looks-like-front", 0)
    assert row.new_tag is None and row.sha256 == ""


@pytest.mark.parametrize(
    ("make_data", "reason"),
    [
        (lambda good: b"this is not an image", "unreadable"),
        (lambda good: good[: len(good) // 2], "unreadable"),
        (
            lambda good: good[:2] + segment(APP1, EXIF_HEADER + b"junk, not a TIFF") + good[2:],
            "exif-malformed",
        ),
    ],
    ids=["not an image", "truncated", "junk exif"],
)
def test_a_bad_file_becomes_a_skip_row_with_a_fixed_reason(
    tmp_path: Path, detector: FaceDetector, make_data, reason: str
) -> None:
    row = decided(tmp_path, detector, make_data(sideways_jpeg(90, 6)))
    assert (row.action, row.reason) == (Action.SKIP, reason)
    assert str(tmp_path) not in row.reason


def test_a_turn_that_cannot_be_written_is_a_skip_not_a_rotate(
    tmp_path: Path, detector: FaceDetector
) -> None:
    pixels = stored_pixels(rotate_cw(load_astronaut(), 90), None)
    data = make_jpeg(pixels, exif=oversized_exif(tag=None))
    row = decided(tmp_path, detector, data)
    assert (row.action, row.reason) == (Action.SKIP, "exif-too-large")


# --- decoding at the detector's size --------------------------------------------------


def test_big_files_are_decoded_near_the_detector_size(tmp_path: Path) -> None:
    pixels = photo_with_face(2400, 3200, 2, (500, 800))
    image = load_working_image(make_jpeg(pixels), None)
    assert image.dtype.name == "uint8" and image.shape[2] == 3
    assert WORKING_LONG_SIDE_PX <= max(image.shape[:2]) < 2 * WORKING_LONG_SIDE_PX


def test_the_orientation_tag_is_applied_before_detection() -> None:
    pixels = textured_photo_without_faces(200, 400)  # 200 rows x 400 columns
    assert load_working_image(make_jpeg(pixels), None).shape[:2] == (200, 400)
    assert load_working_image(make_jpeg(pixels), 6).shape[:2] == (400, 200)
    assert load_working_image(make_jpeg(pixels), 3).shape[:2] == (200, 400)


# --- many files -----------------------------------------------------------------------


def build_library(root: Path) -> list[str]:
    names = ["b/two.jpg", "a/one_a.jpg", "a/one_b.jpg", "c/three.jpg"]
    datas = [sideways_jpeg(90, None), sideways_jpeg(0, 6), sideways_jpeg(180, 1), b"broken"]
    for name, data in zip(names, datas, strict=True):
        write_file(root, name, data)
    return names


def test_rows_come_back_in_the_order_given(tmp_path: Path) -> None:
    names = build_library(tmp_path)
    rows = decide_files(tmp_path, names, jobs=1)
    assert [row.path for row in rows] == names
    assert [row.action for row in rows] == [Action.ROTATE, Action.KEEP, Action.SKIP, Action.SKIP]


def test_worker_processes_give_the_same_rows(tmp_path: Path) -> None:
    names = build_library(tmp_path)
    assert decide_files(tmp_path, names, jobs=2) == decide_files(tmp_path, names, jobs=1)


def test_an_empty_list_needs_no_workers(tmp_path: Path) -> None:
    assert decide_files(tmp_path, [], jobs=3) == ()


def test_a_file_that_vanishes_is_a_skip_row(tmp_path: Path, detector: FaceDetector) -> None:
    row = decide_file(tmp_path, "gone.jpg", detector)
    assert (row.action, row.reason) == (Action.SKIP, "unreadable")


def test_the_library_is_only_read(tmp_path: Path, detector: FaceDetector) -> None:
    data = sideways_jpeg(90, None)
    path = write_file(tmp_path, FRONT, data, mtime_ns=1_000_000_000_000_000_000)
    before = path.stat()
    decide_file(tmp_path, FRONT, detector)
    after = path.stat()
    assert path.read_bytes() == data
    assert after.st_mtime_ns == before.st_mtime_ns
    assert sorted(p.name for p in path.parent.iterdir()) == [path.name]
    assert os.path.exists(path)
