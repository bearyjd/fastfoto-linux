"""``streak_pixels``: which pixels of a band cut's blurred strip are a light streak.

A streak is a run of columns that, in at least ``STREAK_SHARE`` of the rows with backing on both
sides of them (``STREAK_MAX_MM`` away, in whole pixels rounded up) and over at least
``STREAK_MIN_MM`` of such rows, is not backing and is ``STREAK_LIGHTER`` levels brighter than the
brighter of those two neighbours. Its blurred edge, one pixel each side in the same rows, goes with
it. Synthetic arrays, numbers only.
"""

import math

import numpy as np
import pytest

from fastfoto_linux.documents.band import backing_distance
from fastfoto_linux.documents.streak import (
    STREAK_LIGHTER,
    STREAK_MAX_MM,
    STREAK_MIN_MM,
    STREAK_SHARE,
    streak_pixels,
)
from tests.doc_synth import BACKING_RGB

DPI = 300
OFFSET_PX = math.ceil(STREAK_MAX_MM * DPI / 25.4)  # 0.3 mm at 300 dpi is 3.5 pixels: 4
ROWS = 100  # 8.5 mm at 300 dpi
COLUMNS = 60
COLUMN = 30
BACKING = np.asarray(BACKING_RGB, np.float32)


def plus(*levels: float) -> np.ndarray:
    """The backing colour with ``levels`` added to its channels."""
    return BACKING + np.asarray(levels, np.float32)


LIGHT = plus(22, 23, 27)  # 24 levels brighter on average
RINGING = plus(-15, -15, -15)  # a darker fringe next to a light line: not backing, not lighter
SHIFT = (30, -20)  # a hue shift that is far from the backing; the blue channel sets the brightness


def strip(rows: int = ROWS) -> np.ndarray:
    return np.tile(BACKING, (rows, COLUMNS, 1))


def with_line(
    base: np.ndarray, first: int, last: int, rgb, rows: slice = slice(None)
) -> np.ndarray:
    """A copy of ``base`` with columns ``first`` to ``last`` (exclusive) in ``rows`` in ``rgb``."""
    image = base.copy()
    image[rows, first:last] = rgb
    return image


def found(mask: np.ndarray) -> bool:
    return bool(mask.any())


def test_the_constants_are_the_rule() -> None:
    assert (STREAK_MAX_MM, STREAK_LIGHTER, STREAK_SHARE, STREAK_MIN_MM) == (0.3, 4.0, 0.9, 3.0)


def test_a_light_column_in_every_row_is_a_streak_and_the_backing_beside_it_is_not() -> None:
    mask = streak_pixels(with_line(strip(), COLUMN, COLUMN + 1, LIGHT), DPI)
    assert mask[:, COLUMN].all()
    assert mask.sum() == ROWS


def test_the_blurred_edge_one_pixel_each_side_goes_with_the_streak_and_no_more() -> None:
    image = with_line(strip(), COLUMN - 2, COLUMN + 3, RINGING)
    mask = streak_pixels(with_line(image, COLUMN, COLUMN + 1, LIGHT), DPI)
    assert mask[:, COLUMN - 1 : COLUMN + 2].all()
    assert not mask[:, COLUMN - 2].any()
    assert not mask[:, COLUMN + 2].any()


def test_the_edge_goes_with_the_streak_only_in_the_rows_where_it_is() -> None:
    """Half the rows have pad to the left of the line, so they do not count and the line is not
    in them: the fringe beside it is no streak there either."""
    image = with_line(strip(), 0, COLUMN - 2, 255, slice(50, None))
    image = with_line(image, COLUMN + 1, COLUMN + 2, RINGING)
    mask = streak_pixels(with_line(image, COLUMN, COLUMN + 1, LIGHT, slice(0, 50)), DPI)
    assert mask[:50, COLUMN + 1].all()
    assert not mask[50:, COLUMN + 1].any()


def test_an_input_is_never_changed() -> None:
    image = with_line(strip(), COLUMN, COLUMN + 1, LIGHT)
    before = image.copy()
    streak_pixels(image, DPI)
    assert np.array_equal(image, before)


# ---- lighter, by how much ---------------------------------------------------------------------


def hue_shifted(brighter_by: float) -> np.ndarray:
    """A colour 36 from the backing whose mean is ``brighter_by`` over the backing's."""
    blue = 3 * brighter_by - SHIFT[0] - SHIFT[1]
    return plus(SHIFT[0], SHIFT[1], blue)


@pytest.mark.parametrize(("brighter_by", "is_streak"), [(5.0, True), (3.0, False)])
def test_a_line_must_be_a_few_levels_brighter_than_the_backing_beside_it(
    brighter_by: float, is_streak: bool
) -> None:
    rgb = hue_shifted(brighter_by)
    assert backing_distance(rgb[None, None])[0, 0] > 20
    assert STREAK_LIGHTER == 4.0
    assert found(streak_pixels(with_line(strip(), COLUMN, COLUMN + 2, rgb), DPI)) is is_streak


@pytest.mark.parametrize("tone", [150, 100])
def test_a_dark_line_is_not_a_streak(tone: int) -> None:
    assert not found(streak_pixels(with_line(strip(), COLUMN, COLUMN + 2, tone), DPI))


def test_a_line_is_lighter_than_the_brighter_of_its_two_sides() -> None:
    """The right side is backing that is 10 levels brighter; the line is 3 over it, 13 over the
    left."""
    image = with_line(strip(), COLUMN + OFFSET_PX, COLUMNS, plus(10, 10, 10))
    line = np.array([230, 215, 226], np.float32)
    assert line.mean() - plus(10, 10, 10).mean() < STREAK_LIGHTER
    assert not found(streak_pixels(with_line(image, COLUMN, COLUMN + 1, line), DPI))


# ---- how much of the rows ----------------------------------------------------------------------


@pytest.mark.parametrize(("rows", "is_streak"), [(95, True), (80, False)])
def test_a_streak_is_in_nine_tenths_of_the_rows_that_have_backing_on_both_sides(
    rows: int, is_streak: bool
) -> None:
    image = with_line(strip(), COLUMN, COLUMN + 2, LIGHT, slice(0, rows))
    assert found(streak_pixels(image, DPI)) is is_streak


def test_a_streak_in_the_rows_with_backing_on_both_sides_is_a_streak_whatever_the_other_rows() -> (
    None
):
    """Half the rows have pad (white) to one side of the line: they are not counted."""
    image = with_line(strip(), 0, COLUMN - 2, 255, slice(50, None))
    image = with_line(image, COLUMN, COLUMN + 2, LIGHT, slice(0, 50))
    assert streak_pixels(image, DPI)[:50, COLUMN].all()


@pytest.mark.parametrize(("rows", "is_streak"), [(40, True), (30, False)])
def test_a_streak_is_over_three_millimetres_of_rows(rows: int, is_streak: bool) -> None:
    """40 rows are 3.4 mm at 300 dpi, 30 rows are 2.5 mm."""
    image = with_line(strip(rows), COLUMN, COLUMN + 2, LIGHT)
    assert found(streak_pixels(image, DPI)) is is_streak


# ---- how wide ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("columns", "is_streak"),
    [(2, True), (2 * OFFSET_PX - 1, True), (2 * OFFSET_PX, False), (12, False)],
)
def test_a_streak_has_backing_within_the_width_on_both_sides(columns: int, is_streak: bool) -> None:
    """A line of 12 pixels is 1 mm. Backing lies ``OFFSET_PX`` away on each side of every pixel of
    a streak, so a line is at most twice that wide, less the pixel itself."""
    image = with_line(strip(), COLUMN, COLUMN + columns, LIGHT)
    assert found(streak_pixels(image, DPI)) is is_streak


def test_the_width_is_never_under_two_pixels_whatever_the_resolution() -> None:
    """At 50 dpi 0.3 mm is under a pixel: a line of three pixels is still the most one can be."""
    image = with_line(strip(), COLUMN, COLUMN + 3, LIGHT)
    assert found(streak_pixels(image, 50))
    assert not found(streak_pixels(with_line(strip(), COLUMN, COLUMN + 4, LIGHT), 50))
