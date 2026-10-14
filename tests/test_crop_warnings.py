"""Log messages and the plausibility flag of the photo finder."""

import logging

import pytest

from fastfoto_linux.pipeline.crop import Detection, detect_photo, find_photo_box
from fastfoto_linux.pipeline.geometry import mm_to_px
from tests.crop_helpers import CROP_LOGGER, SIDES, assert_box_matches
from tests.synth import BACKGROUND_RGB, make_frame

PRINT_SIZES = {
    "4x6": (152, 102),
    "5x7": (178, 127),
    "8x10": (254, 203),
    "panorama": (250, 90),
}


def warnings_for(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]


@pytest.mark.parametrize("side", SIDES)
@pytest.mark.parametrize("size", PRINT_SIZES.values(), ids=PRINT_SIZES.keys())
def test_common_print_sizes_are_plausible_and_silent(
    size: tuple[float, float], side: str, caplog: pytest.LogCaptureFixture
) -> None:
    frame, expected = make_frame(photo_mm=size, side=side)
    with caplog.at_level(logging.DEBUG, logger=CROP_LOGGER):
        detection = detect_photo(frame, 150)
    assert isinstance(detection, Detection)
    assert detection.plausible
    assert_box_matches(detection.box, expected, 150)
    assert not warnings_for(caplog)


def test_find_photo_box_returns_the_detection_box() -> None:
    frame, _ = make_frame(dpi=75)
    assert find_photo_box(frame, 75) == detect_photo(frame, 75).box


def test_sky_coloured_top_is_flagged_implausible_with_the_likely_cause(
    caplog: pytest.LogCaptureFixture,
) -> None:
    frame, _ = make_frame(dpi=150, sky_mm=44)
    with caplog.at_level(logging.WARNING, logger=CROP_LOGGER):
        detection = detect_photo(frame, 150)
    assert not detection.plausible
    messages = warnings_for(caplog)
    assert any("no common print size" in m and "background colour" in m for m in messages)


def test_find_photo_box_also_warns_for_an_implausible_size(
    caplog: pytest.LogCaptureFixture,
) -> None:
    frame, _ = make_frame(dpi=150, sky_mm=44)
    with caplog.at_level(logging.WARNING, logger=CROP_LOGGER):
        find_photo_box(frame, 150)
    assert any("no common print size" in m for m in warnings_for(caplog))


def test_unusual_sized_cream_back_is_returned_but_flagged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    frame, expected = make_frame(
        dpi=150, side="back", photo_mm=(120, 60), photo_rgb=(235, 228, 210), imprint=False
    )
    with caplog.at_level(logging.WARNING, logger=CROP_LOGGER):
        detection = detect_photo(frame, 150)
    assert not detection.plausible
    assert_box_matches(detection.box, expected, 150)
    assert any("no common print size" in m for m in warnings_for(caplog))


@pytest.mark.xfail(
    strict=True,
    reason="a sky-coloured top edge is cropped away; the sides PR corrects the front box from "
    "the back box",
)
def test_sky_coloured_top_is_still_inside_the_box() -> None:
    frame, expected = make_frame(dpi=150, sky_mm=44)
    assert_box_matches(find_photo_box(frame, 150), expected, 150)


def test_top_edge_is_normal_for_adf_scans_and_only_logged_at_debug(
    caplog: pytest.LogCaptureFixture,
) -> None:
    frame, expected = make_frame(offset_mm=(20, 0))
    with caplog.at_level(logging.DEBUG, logger=CROP_LOGGER):
        box = find_photo_box(frame, 150)
    assert box.y == 0
    assert_box_matches(box, expected, 150)
    assert not warnings_for(caplog)
    assert any(r.levelno == logging.DEBUG and "top" in r.getMessage() for r in caplog.records)


def test_left_edge_warning_names_the_side(caplog: pytest.LogCaptureFixture) -> None:
    frame, expected = make_frame(offset_mm=(0, 0.5), white_strip=None)
    with caplog.at_level(logging.WARNING, logger=CROP_LOGGER):
        box = find_photo_box(frame, 150)
    assert box.x == 0
    assert_box_matches(box, expected, 150)
    assert any("left frame edge" in m for m in warnings_for(caplog))
    assert not any("right" in m or "bottom" in m for m in warnings_for(caplog))


def test_right_edge_is_detected_when_the_width_is_not_a_multiple_of_the_downsample_factor(
    caplog: pytest.LogCaptureFixture,
) -> None:
    frame, expected = make_frame(dpi=150, right_margin_mm=0, white_strip=None)
    assert frame.shape[1] % 2 == 1  # 150 dpi downsamples by 2
    with caplog.at_level(logging.WARNING, logger=CROP_LOGGER):
        box = find_photo_box(frame, 150)
    assert box.x + box.w == frame.shape[1]
    assert_box_matches(box, expected, 150)
    assert any("right frame edge" in m for m in warnings_for(caplog))


def test_bottom_edge_is_detected_when_the_height_is_not_a_multiple_of_the_downsample_factor(
    caplog: pytest.LogCaptureFixture,
) -> None:
    frame, expected = make_frame(dpi=150, grey_band_mm=0, tail_mm=0)
    assert frame.shape[0] % 2 == 1
    with caplog.at_level(logging.WARNING, logger=CROP_LOGGER):
        box = find_photo_box(frame, 150)
    assert box.y + box.h == frame.shape[0]
    assert_box_matches(box, expected, 150)
    assert any("bottom frame edge" in m for m in warnings_for(caplog))


def test_photo_clear_of_the_edges_logs_no_warning(caplog: pytest.LogCaptureFixture) -> None:
    frame, _ = make_frame(offset_mm=(20, 5))
    with caplog.at_level(logging.WARNING, logger=CROP_LOGGER):
        find_photo_box(frame, 150)
    assert not caplog.records


def test_a_second_photo_sized_region_is_reported_and_the_largest_returned(
    caplog: pytest.LogCaptureFixture,
) -> None:
    frame, expected = make_frame(dpi=75, right_margin_mm=100)
    left = expected.x + expected.w + mm_to_px(20, 75)
    frame[mm_to_px(10, 75) : mm_to_px(60, 75), left : left + mm_to_px(60, 75)] = 40
    with caplog.at_level(logging.WARNING, logger=CROP_LOGGER):
        box = find_photo_box(frame, 75)
    assert_box_matches(box, expected, 75)
    assert any("ignored 1 other photo-sized region" in m for m in warnings_for(caplog))


def test_dark_patch_under_25_mm_beside_the_photo_is_not_a_second_photo(
    caplog: pytest.LogCaptureFixture,
) -> None:
    frame, expected = make_frame(dpi=75, right_margin_mm=100)
    left = expected.x + expected.w + mm_to_px(20, 75)
    frame[mm_to_px(10, 75) : mm_to_px(30, 75), left : left + mm_to_px(60, 75)] = 40  # 60 x 20 mm
    with caplog.at_level(logging.WARNING, logger=CROP_LOGGER):
        find_photo_box(frame, 75)
    assert not warnings_for(caplog)


def test_pale_fragment_inside_the_photo_box_is_not_a_second_photo(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Background-coloured stripes can cut a 30 x 40 mm corner off the photo; it is still one."""
    frame, expected = make_frame(dpi=75)
    stripe = mm_to_px(5, 75)
    cut_x = expected.x + expected.w - mm_to_px(35, 75)
    cut_y = expected.y + mm_to_px(40, 75)
    frame[expected.y : cut_y + stripe, cut_x : cut_x + stripe] = BACKGROUND_RGB
    frame[cut_y : cut_y + stripe, cut_x : expected.x + expected.w] = BACKGROUND_RGB
    with caplog.at_level(logging.WARNING, logger=CROP_LOGGER):
        box = find_photo_box(frame, 75)
    assert_box_matches(box, expected, 75)
    assert not any("ignored" in m for m in warnings_for(caplog))
