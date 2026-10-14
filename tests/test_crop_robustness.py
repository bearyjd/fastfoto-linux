"""Harder real-world cases for the photo finder.

Each test pins one algorithm constant: pushing the matching constant far off makes it fail.
"""

import numpy as np
import pytest

from fastfoto_linux.pipeline.crop import NoPhotoFoundError, find_photo_box
from fastfoto_linux.pipeline.geometry import mm_to_px
from tests.crop_helpers import SIDES, assert_box_matches, background_only
from tests.synth import BACKGROUND_RGB, make_frame

LONG_TAIL_MM = 250  # real frames are 393 mm tall, most of it white tail
FRAME_WIDTH_MM = 215.9
CREAM_PAPER = [(235, 228, 210), (225, 222, 215)]
PALE_PRINT = (165, 180, 200)  # about 50 RGB units from the scanner background


def with_defect_rows(frame: np.ndarray, rows: int) -> np.ndarray:
    """Copy of ``frame`` with ``rows`` grey rows, 3% of the width, 85% of the way down."""
    out = frame.copy()
    first = int(out.shape[0] * 0.85)
    out[first : first + rows, : int(out.shape[1] * 0.03)] = 128
    return out


@pytest.mark.parametrize("side", SIDES)
@pytest.mark.parametrize("rows", [1, 2, 3, 9])  # 9 rows at 75 dpi is a 3 mm streak
def test_defect_rows_in_a_long_tail_do_not_move_the_box(side: str, rows: int) -> None:
    frame, expected = make_frame(dpi=75, side=side, tail_mm=LONG_TAIL_MM)
    assert_box_matches(find_photo_box(with_defect_rows(frame, rows), 75), expected, 75)


@pytest.mark.parametrize("side", SIDES)
def test_defect_rows_are_tolerated_at_300_dpi(side: str) -> None:
    frame, expected = make_frame(dpi=300, photo_mm=(100, 70), side=side, tail_mm=100)
    assert_box_matches(find_photo_box(with_defect_rows(frame, 2), 300), expected, 300)


@pytest.mark.parametrize("side", SIDES)
@pytest.mark.parametrize("width_mm", [205, 208, 211, 213])
def test_prints_nearly_as_wide_as_the_frame(side: str, width_mm: int) -> None:
    margin = (FRAME_WIDTH_MM - width_mm) / 2
    frame, expected = make_frame(
        dpi=75,
        side=side,
        photo_mm=(width_mm, 127),
        offset_mm=(margin, 0.5),
        right_margin_mm=margin,
        white_strip=None,
        tail_mm=LONG_TAIL_MM,
    )
    assert_box_matches(find_photo_box(frame, 75), expected, 75)


def test_wide_back_at_300_dpi() -> None:
    frame, expected = make_frame(
        dpi=300,
        side="back",
        photo_mm=(208, 60),
        offset_mm=(3.95, 0.5),
        right_margin_mm=3.95,
        white_strip=None,
        tail_mm=80,
    )
    assert_box_matches(find_photo_box(frame, 300), expected, 300)


def test_pure_white_back_98_percent_of_the_frame_width_is_not_tail() -> None:
    """Every paper row is white enough to look like tail; only the grey band tells them apart."""
    margin = (FRAME_WIDTH_MM - 213) / 2
    frame, expected = make_frame(
        dpi=75,
        side="back",
        photo_mm=(213, 127),
        offset_mm=(margin, 0.5),
        right_margin_mm=margin,
        white_strip=None,
        photo_rgb=(255, 255, 255),
        paper_noise_std=0,
        imprint=False,
        tail_mm=LONG_TAIL_MM,
    )
    assert_box_matches(find_photo_box(frame, 75), expected, 75)


def test_wide_print_beside_the_white_strip() -> None:
    frame, expected = make_frame(
        dpi=75,
        photo_mm=(205, 127),
        offset_mm=(5.45, 0.5),
        right_margin_mm=5.45,
        white_strip="right",
        tail_mm=LONG_TAIL_MM,
    )
    assert_box_matches(find_photo_box(frame, 75), expected, 75)


def test_white_paper_directly_above_the_tail_is_not_tail() -> None:
    """With no grey band, paper rows 94% white must not be mistaken for tail rows."""
    frame, expected = make_frame(
        dpi=75,
        side="back",
        photo_mm=(208, 127),
        offset_mm=(3.95, 0.5),
        right_margin_mm=3.95,
        white_strip=None,
        grey_band_mm=0,
        photo_rgb=(254, 254, 254),
        imprint=False,
        tail_mm=LONG_TAIL_MM,
    )
    assert_box_matches(find_photo_box(frame, 75), expected, 75)


@pytest.mark.parametrize("strip", ["left", "right"])
def test_edge_strip_running_through_the_tail_does_not_hide_it(strip: str) -> None:
    frame, expected = make_frame(
        dpi=75, white_strip=strip, strip_through_tail=True, tail_mm=LONG_TAIL_MM
    )
    assert_box_matches(find_photo_box(frame, 75), expected, 75)


@pytest.mark.parametrize("side", SIDES)
def test_slightly_off_white_tail_is_still_tail(side: str) -> None:
    frame, expected = make_frame(
        dpi=75, photo_mm=(60, 40), side=side, tail_grey=251, tail_mm=LONG_TAIL_MM
    )
    assert_box_matches(find_photo_box(frame, 75), expected, 75)


@pytest.mark.parametrize("rgb", CREAM_PAPER)
@pytest.mark.parametrize("dpi", [75, 150])
def test_cream_or_aged_backs_are_found(rgb: tuple[int, int, int], dpi: int) -> None:
    frame, expected = make_frame(dpi=dpi, side="back", photo_rgb=rgb, imprint=False)
    assert_box_matches(find_photo_box(frame, dpi), expected, dpi)


@pytest.mark.parametrize("rgb", CREAM_PAPER)
def test_cream_back_with_imprint_and_handwriting(rgb: tuple[int, int, int]) -> None:
    frame, expected = make_frame(
        dpi=150, side="back", photo_rgb=rgb, imprint=True, writing=True, rng_seed=2
    )
    assert_box_matches(find_photo_box(frame, 150), expected, 150)


@pytest.mark.parametrize("side", SIDES)
@pytest.mark.parametrize("blur_mm", [0.2, 0.5, 0.85])
def test_rolled_off_photo_edges(side: str, blur_mm: float) -> None:
    frame, expected = make_frame(dpi=150, side=side, edge_blur_mm=blur_mm)
    assert_box_matches(find_photo_box(frame, 150), expected, 150)


def test_rolled_off_edges_on_cream_paper() -> None:
    frame, expected = make_frame(
        dpi=150, side="back", photo_rgb=CREAM_PAPER[0], imprint=False, edge_blur_mm=0.5
    )
    assert_box_matches(find_photo_box(frame, 150), expected, 150)


@pytest.mark.parametrize("side", SIDES)
def test_soft_shadow_ring_is_not_part_of_the_print(side: str) -> None:
    frame, expected = make_frame(dpi=150, side=side, halo_mm=4)
    assert_box_matches(find_photo_box(frame, 150), expected, 150)


def test_pale_print_with_a_shadow_ring_is_found_at_the_strict_threshold() -> None:
    frame, expected = make_frame(dpi=150, photo_rgb=PALE_PRINT, halo_mm=4)
    assert_box_matches(find_photo_box(frame, 150), expected, 150)


def test_background_is_measured_from_the_frame_not_assumed() -> None:
    """Background 16 units off the usual colour, paper 25 from it but only 10 from the usual."""
    frame, expected = make_frame(
        dpi=150,
        side="back",
        background_rgb=(193, 201, 210),
        photo_rgb=(210, 215, 222),
        paper_noise_std=1,
        imprint=False,
    )
    assert_box_matches(find_photo_box(frame, 150), expected, 150)


def test_faint_stain_is_not_a_photo() -> None:
    frame = background_only(150, (200, 200))
    top, left, height, width = 40, 50, mm_to_px(60, 150), mm_to_px(40, 150)
    stain = frame[top : top + height, left : left + width].astype(np.int16) - 9
    frame[top : top + height, left : left + width] = np.clip(stain, 0, 255).astype(np.uint8)
    with pytest.raises(NoPhotoFoundError):
        find_photo_box(frame, 150)


def test_thin_hair_touching_the_photo_does_not_stretch_the_box() -> None:
    frame, expected = make_frame(dpi=150, offset_mm=(20, 20))
    hair = slice(expected.y - mm_to_px(15, 150), expected.y)
    middle = expected.x + expected.w // 2
    frame[hair, middle : middle + mm_to_px(0.6, 150)] = 30
    assert_box_matches(find_photo_box(frame, 150), expected, 150)


def test_thin_border_around_a_pale_picture_is_kept() -> None:
    frame, expected = make_frame(dpi=150)
    border = mm_to_px(4, 150)
    inner = (
        slice(expected.y + border, expected.y + expected.h - border),
        slice(expected.x + border, expected.x + expected.w - border),
    )
    frame[inner] = BACKGROUND_RGB
    assert_box_matches(find_photo_box(frame, 150), expected, 150)


def test_fully_pale_frame_without_contrast_has_no_photo() -> None:
    with pytest.raises(NoPhotoFoundError):
        find_photo_box(background_only(150), 150)
