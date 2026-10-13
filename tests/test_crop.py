import dataclasses
import logging

import numpy as np
import pytest

from fastfoto_linux.pipeline.crop import Box, NoPhotoFoundError, crop, find_photo_box
from fastfoto_linux.pipeline.geometry import mm_to_px
from tests.synth import BACKGROUND_RGB, make_frame

TOLERANCE_MM = 1.0
PHOTO_4X6 = (152, 102)
PHOTO_5X7 = (178, 127)
PHOTO_8X10 = (254, 203)
PANORAMA = (250, 90)
SIDES = ("front", "back")


def assert_box_matches(found: Box, expected: Box, dpi: int) -> None:
    """Every edge within TOLERANCE_MM (numbers only in the failure message)."""
    fx, fy, fw, fh = found.mm(dpi)
    ex, ey, ew, eh = expected.mm(dpi)
    edges = {
        "left": (fx, ex),
        "top": (fy, ey),
        "right": (fx + fw, ex + ew),
        "bottom": (fy + fh, ey + eh),
    }
    off = {name: round(f - e, 2) for name, (f, e) in edges.items() if abs(f - e) > TOLERANCE_MM}
    assert not off, f"edges off by more than {TOLERANCE_MM} mm at {dpi} dpi: {off}"


def background_only(dpi: int, size_mm: tuple[float, float] = (120, 150)) -> np.ndarray:
    rng = np.random.default_rng(1)
    shape = (mm_to_px(size_mm[1], dpi), mm_to_px(size_mm[0], dpi), 3)
    noise = rng.normal(0, 3, size=shape)
    return np.clip(np.asarray(BACKGROUND_RGB) + noise, 0, 255).astype(np.uint8)


@pytest.mark.parametrize("side", SIDES)
@pytest.mark.parametrize("dpi", [75, 150, 300])
def test_finds_photo_across_resolutions(dpi: int, side: str) -> None:
    frame, expected = make_frame(dpi=dpi, side=side)
    assert_box_matches(find_photo_box(frame, dpi), expected, dpi)


@pytest.mark.parametrize("side", SIDES)
def test_finds_photo_at_600_dpi_on_a_small_frame(side: str) -> None:
    frame, expected = make_frame(dpi=600, photo_mm=(60, 40), side=side, tail_mm=15)
    assert_box_matches(find_photo_box(frame, 600), expected, 600)


@pytest.mark.parametrize("side", SIDES)
@pytest.mark.parametrize("photo_mm", [PHOTO_4X6, PHOTO_5X7, PHOTO_8X10, PANORAMA])
def test_finds_photos_of_each_size(photo_mm: tuple[float, float], side: str) -> None:
    frame, expected = make_frame(photo_mm=photo_mm, side=side)
    assert_box_matches(find_photo_box(frame, 150), expected, 150)


@pytest.mark.parametrize("side", SIDES)
@pytest.mark.parametrize(
    ("offset_x", "right_margin"), [(20, 18), (10, 18), (18, 10), (14, 36)], ids=str
)
def test_finds_photo_close_to_either_side_edge(
    side: str, offset_x: float, right_margin: float
) -> None:
    frame, expected = make_frame(
        offset_mm=(offset_x, 0.5), right_margin_mm=right_margin, side=side, white_strip="right"
    )
    assert_box_matches(find_photo_box(frame, 150), expected, 150)


@pytest.mark.parametrize("side", SIDES)
@pytest.mark.parametrize("strip", ["left", "right", None])
def test_white_edge_strip_is_not_part_of_the_photo(side: str, strip: str | None) -> None:
    frame, expected = make_frame(side=side, white_strip=strip, offset_mm=(12, 0.5))
    assert_box_matches(find_photo_box(frame, 150), expected, 150)


def test_back_with_imprint_and_handwriting_is_still_found() -> None:
    frame, expected = make_frame(side="back", imprint=True, writing=True, rng_seed=5)
    assert_box_matches(find_photo_box(frame, 150), expected, 150)


def test_front_with_background_coloured_interior_uses_component_bounding_box() -> None:
    frame, expected = make_frame(side="front")
    hole = frame.copy()
    inner = Box(
        expected.x + expected.w // 4, expected.y + expected.h // 4, expected.w // 2, expected.h // 2
    )
    hole[inner.y : inner.y + inner.h, inner.x : inner.x + inner.w] = BACKGROUND_RGB
    assert_box_matches(find_photo_box(hole, 150), expected, 150)


def test_frame_without_a_tail_is_handled() -> None:
    frame, expected = make_frame(tail_mm=0, side="back")
    assert_box_matches(find_photo_box(frame, 150), expected, 150)


@pytest.mark.parametrize("side", SIDES)
def test_long_white_tail_is_not_mistaken_for_the_photo(side: str) -> None:
    frame, expected = make_frame(dpi=75, photo_mm=(60, 40), side=side, tail_mm=250)
    assert_box_matches(find_photo_box(frame, 75), expected, 75)


def test_find_photo_box_does_not_mutate_its_input() -> None:
    frame, _ = make_frame(side="back", writing=True)
    snapshot = frame.copy()
    find_photo_box(frame, 150)
    assert np.array_equal(frame, snapshot)
    frame.setflags(write=False)
    find_photo_box(frame, 150)  # a read-only array must be accepted


def test_non_contiguous_input_is_accepted() -> None:
    frame, expected = make_frame()
    reversed_rows = np.ascontiguousarray(frame[::-1])[::-1]
    assert not frame[:, ::2].flags.c_contiguous
    assert_box_matches(find_photo_box(reversed_rows, 150), expected, 150)


@pytest.mark.parametrize("dpi", [75, 300])
def test_background_only_frame_has_no_photo(dpi: int) -> None:
    with pytest.raises(NoPhotoFoundError):
        find_photo_box(background_only(dpi), dpi)


def test_all_white_frame_has_no_photo() -> None:
    with pytest.raises(NoPhotoFoundError):
        find_photo_box(np.full((300, 200, 3), 255, dtype=np.uint8), 75)


def test_blob_smaller_than_25_mm_is_not_a_photo() -> None:
    frame = background_only(150)
    side = mm_to_px(10, 150)
    frame[200 : 200 + side, 300 : 300 + side] = (30, 30, 30)
    with pytest.raises(NoPhotoFoundError, match="25"):
        find_photo_box(frame, 150)


def test_one_dimension_below_25_mm_is_rejected_but_25_mm_photo_passes() -> None:
    frame, _ = make_frame(photo_mm=(120, 20))
    with pytest.raises(NoPhotoFoundError):
        find_photo_box(frame, 150)
    frame, expected = make_frame(photo_mm=(30, 30))
    assert_box_matches(find_photo_box(frame, 150), expected, 150)


def test_no_photo_error_is_a_value_error() -> None:
    assert issubclass(NoPhotoFoundError, ValueError)


def test_touching_the_frame_edge_logs_a_warning(caplog: pytest.LogCaptureFixture) -> None:
    frame, expected = make_frame(offset_mm=(20, 0))
    with caplog.at_level(logging.WARNING, logger="fastfoto_linux.pipeline.crop"):
        box = find_photo_box(frame, 150)
    assert box.y == 0
    assert any("frame edge" in record.message for record in caplog.records)
    assert_box_matches(box, expected, 150)


def test_photo_clear_of_the_edges_logs_no_warning(caplog: pytest.LogCaptureFixture) -> None:
    frame, _ = make_frame(offset_mm=(20, 5))
    with caplog.at_level(logging.WARNING, logger="fastfoto_linux.pipeline.crop"):
        find_photo_box(frame, 150)
    assert not caplog.records


@pytest.mark.parametrize(
    "frame",
    [
        np.zeros((100, 100), dtype=np.uint8),
        np.zeros((100, 100, 4), dtype=np.uint8),
        np.zeros((100, 100, 3), dtype=np.float32),
    ],
    ids=["grey", "rgba", "float"],
)
def test_malformed_frames_are_rejected(frame: np.ndarray) -> None:
    with pytest.raises(ValueError, match="HxWx3 uint8"):
        find_photo_box(frame, 150)


def test_frame_too_narrow_to_sample_background_is_rejected() -> None:
    with pytest.raises(ValueError, match="too narrow"):
        find_photo_box(np.zeros((200, 20, 3), dtype=np.uint8), 75)


def test_box_reports_millimetres() -> None:
    assert Box(150, 300, 600, 1200).mm(150) == pytest.approx((25.4, 50.8, 101.6, 203.2))


def test_box_is_frozen_and_requires_positive_size() -> None:
    box = Box(1, 2, 3, 4)
    with pytest.raises(dataclasses.FrozenInstanceError):
        box.x = 5  # type: ignore[misc]
    for w, h in ((0, 4), (3, 0), (-1, 4)):
        with pytest.raises(ValueError, match="positive size"):
            Box(0, 0, w, h)


def test_crop_returns_an_independent_copy_of_the_box_region() -> None:
    frame, box = make_frame(dpi=75)
    snapshot = frame.copy()
    cut = crop(frame, box)
    assert cut.shape == (box.h, box.w, 3)
    assert np.array_equal(cut, frame[box.y : box.y + box.h, box.x : box.x + box.w])
    cut[:] = 0
    assert np.array_equal(frame, snapshot)
    assert not np.shares_memory(cut, frame)


def test_crop_of_found_box_contains_only_photo_pixels() -> None:
    frame, _ = make_frame(side="back", imprint=False)
    cut = crop(frame, find_photo_box(frame, 150))
    assert np.median(cut) > 240


@pytest.mark.parametrize(
    "box", [Box(-1, 0, 10, 10), Box(0, -1, 10, 10), Box(95, 0, 10, 10), Box(0, 95, 10, 10)]
)
def test_crop_rejects_boxes_outside_the_frame(box: Box) -> None:
    with pytest.raises(ValueError, match="outside"):
        crop(np.zeros((100, 100, 3), dtype=np.uint8), box)
