import numpy as np
import pytest

from fastfoto_linux.pipeline.geometry import mm_to_px
from tests.synth import MIRROR_X_OFFSET_MM, make_duplex_sheet

DPI = 150


def test_frames_share_a_width_within_a_pixel() -> None:
    (front, _), (back, _) = make_duplex_sheet(dpi=DPI)
    assert abs(front.shape[1] - back.shape[1]) <= 1


def test_front_box_is_the_back_box_mirrored_in_x_and_shifted() -> None:
    (front, front_box), (_, back_box) = make_duplex_sheet(dpi=DPI)
    expected_x = front.shape[1] - (back_box.x + back_box.w) + mm_to_px(MIRROR_X_OFFSET_MM, DPI)
    assert front_box.x == pytest.approx(expected_x, abs=1)
    assert front_box.y == back_box.y
    assert (front_box.w, front_box.h) == pytest.approx((back_box.w, back_box.h), abs=1)


def test_front_is_a_dark_photo_and_back_is_white_paper() -> None:
    (front, front_box), (back, back_box) = make_duplex_sheet(dpi=DPI)
    assert np.median(front[front_box.y : front_box.y + front_box.h]) < 150
    assert np.median(back[back_box.y : back_box.y + back_box.h]) > 240


def test_per_side_arguments_reach_make_frame() -> None:
    (front, front_box), (back, back_box) = make_duplex_sheet(
        dpi=DPI, front={"sky_mm": 20}, back={"writing": True, "imprint": False}
    )
    top = front[front_box.y : front_box.y + mm_to_px(20, DPI), front_box.x : front_box.x + 50]
    assert top.reshape(-1, 3).mean(axis=0) == pytest.approx((190, 203, 222), abs=2)
    assert (back[back_box.y : back_box.y + back_box.h] < 150).any()


def test_edge_strips_are_on_opposite_sides() -> None:
    (front, front_box), (back, back_box) = make_duplex_sheet(dpi=DPI)
    assert front[front_box.y + 5, 0].mean() > 240
    assert back[back_box.y + 5, -1].mean() > 240
