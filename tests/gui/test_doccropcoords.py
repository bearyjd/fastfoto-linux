"""A drag on the painted page becomes a crop in page units, or nothing."""

import math

import pytest

from fastfoto_linux.documents.page_crop import PageCrop
from fastfoto_linux.gui.doccropcoords import crop_rect, drag_to_crop

# A 1000 x 2000 px page at 254 dpi (5 mm = 50 px) painted 500 x 1000 inside a 600 x 1200 item:
# 50 px of margin left and right, 100 px above and below.
GEOMETRY = {
    "size": (1000, 2000),
    "dpi": 254,
    "painted_width": 500.0,
    "painted_height": 1000.0,
    "item_width": 600.0,
    "item_height": 1200.0,
}


def test_a_drag_across_the_letterboxed_page_gives_the_page_units():
    crop = drag_to_crop(100, 200, 500, 1000, **GEOMETRY)
    assert crop == PageCrop(1000, 1000, 9000, 9000)


def test_the_corners_may_be_dragged_in_any_order():
    assert drag_to_crop(500, 1000, 100, 200, **GEOMETRY) == PageCrop(1000, 1000, 9000, 9000)


def test_a_drag_outside_the_painted_page_clamps_to_it():
    crop = drag_to_crop(-50, -50, 900, 1500, **GEOMETRY)
    assert crop == PageCrop(0, 0, 10_000, 10_000)


def test_under_five_millimetres_is_refused():
    # 24 painted px across is 48 page px: under the 50 px minimum.
    assert drag_to_crop(100, 200, 124, 1000, **GEOMETRY) is None
    assert drag_to_crop(100, 200, 500, 224, **GEOMETRY) is None


def test_exactly_five_millimetres_is_accepted():
    assert drag_to_crop(100, 200, 125, 225, **GEOMETRY) is not None


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_unusable_numbers_give_none(bad):
    assert drag_to_crop(bad, 200, 500, 1000, **GEOMETRY) is None
    assert drag_to_crop(100, 200, 500, 1000, **{**GEOMETRY, "painted_width": bad}) is None


@pytest.mark.parametrize(
    "override",
    [
        {"painted_width": 0.0},
        {"painted_height": 0.0},
        {"item_width": 0.0},
        {"size": (0, 2000)},
        {"size": (1000, 0)},
        {"dpi": 0},
        {"dpi": -300},
    ],
)
def test_zero_sizes_and_dpi_give_none(override):
    assert drag_to_crop(100, 200, 500, 1000, **{**GEOMETRY, **override}) is None


def test_the_drawn_rectangle_is_the_pixel_box_that_will_be_written():
    crop = PageCrop(1000, 1000, 9000, 9000)
    assert crop_rect(crop, (1000, 2000), 254) == (100, 200, 900, 1800)


def test_the_drawn_rectangle_shows_the_minimum_a_small_page_grows_to():
    # 3 units of 10 000 on a 1000 px side is under a pixel: the written box is 50 px (5 mm).
    left, top, right, bottom = crop_rect(PageCrop(5000, 5000, 5003, 5003), (1000, 2000), 254)
    assert (right - left, bottom - top) == (50, 50)
