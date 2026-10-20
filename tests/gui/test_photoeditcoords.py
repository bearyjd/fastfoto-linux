"""Canonical coordinates preserve letterboxing, precision and normalized geometry."""

import pytest

from fastfoto_linux.gui.photoeditcoords import source_crop, source_ellipse, source_point

GEOMETRY = dict(
    source_width=4000,
    source_height=2000,
    painted_width=800.0,
    painted_height=400.0,
    item_width=800.0,
    item_height=600.0,
)


@pytest.mark.parametrize(
    "point,expected",
    [((0, 100), (0, 0)), ((400, 300), (2000, 1000)), ((200.25, 200.5), (1001.25, 502.5))],
)
def test_letterbox_origin_and_subpixel_precision(point, expected):
    assert source_point(*point, **GEOMETRY) == pytest.approx(expected)


@pytest.mark.parametrize("point", [(100, 99), (100, 501), (-1, 200), (801, 200)])
def test_letterbox_margins_are_ignored(point):
    assert source_point(*point, **GEOMETRY) is None


def test_drag_direction_does_not_change_canonical_ellipse():
    expected = (2000, 1000, 500, 250)
    assert source_ellipse(300, 250, 500, 350, **GEOMETRY) == pytest.approx(expected)
    assert source_ellipse(500, 350, 300, 250, **GEOMETRY) == pytest.approx(expected)


def test_upright_portrait_coordinates_use_normalized_source_dimensions():
    geometry = dict(
        source_width=2000,
        source_height=4000,
        painted_width=300.0,
        painted_height=600.0,
        item_width=800.0,
        item_height=600.0,
    )
    assert source_point(400, 300, **geometry) == pytest.approx((1000, 2000))


@pytest.mark.parametrize("value", [0, float("nan"), float("inf")])
def test_unpainted_and_invalid_dimensions_are_ignored(value):
    assert source_point(400, 300, **(GEOMETRY | {"painted_width": value})) is None


@pytest.mark.parametrize("point", [(float("nan"), 300), (400, float("inf"))])
def test_nonfinite_pointer_is_ignored(point):
    assert source_point(*point, **GEOMETRY) is None


CROP_GEOMETRY = dict(GEOMETRY, source_width=1000, source_height=500)
MINIMUM = dict(min_width=100, min_height=50)


def crop(*points, **overrides):
    return source_crop(*points, **{**CROP_GEOMETRY, **MINIMUM, **overrides})


def test_crop_maps_floor_and_ceil_to_whole_source_pixels():
    # 800 painted px span 1000 source px, so one painted px is 1.25 source px.
    assert crop(100.4, 150.2, 500.0, 350.0) == (125, 62, 625, 313)
    assert crop(100.0, 140.0, 500.0, 340.0) == (125, 50, 625, 300)


def test_crop_drag_direction_does_not_change_the_rectangle():
    forward = crop(100, 150, 500, 350)
    assert forward == crop(500, 350, 100, 150) == crop(500, 150, 100, 350)


def test_crop_clamps_points_outside_the_painted_rect_and_letterbox():
    assert crop(-50, 20, 900, 700) == (0, 0, 1000, 500)
    assert crop(-50, 20, 400, 700) == (0, 0, 500, 500)


def test_crop_below_the_minimum_on_either_side_is_none():
    assert crop(100, 150, 120, 350) is None
    assert crop(100, 150, 500, 160) is None
    assert crop(100, 150, 500, 350, min_width=1000) is None
    assert crop(100, 150, 500, 350, min_height=1) == (125, 62, 625, 313)


def test_crop_rejects_non_finite_and_non_positive_inputs():
    assert crop(float("nan"), 150, 500, 350) is None
    assert crop(100, float("inf"), 500, 350) is None
    assert crop(100, 150, 500, 350, painted_width=0.0) is None
    assert crop(100, 150, 500, 350, source_height=0) is None
    assert crop(100, 150, 500, 350, item_width=-1.0) is None


def test_crop_uses_source_dimensions_of_a_portrait_letterbox():
    portrait = dict(
        source_width=500,
        source_height=1000,
        painted_width=300.0,
        painted_height=600.0,
        item_width=800.0,
        item_height=600.0,
    )
    result = crop(250, 0, 550, 600, **portrait)
    assert result == (0, 0, 500, 1000)
