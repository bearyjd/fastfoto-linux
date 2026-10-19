"""Canonical coordinates preserve letterboxing, precision and normalized geometry."""

import pytest

from fastfoto_linux.gui.photoeditcoords import source_ellipse, source_point

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
