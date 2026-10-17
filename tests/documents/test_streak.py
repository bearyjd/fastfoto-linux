"""``streak_pixels``: which pixels of a band cut's blurred strip are a light streak.

A streak is a run of columns that, in at least ``STREAK_SHARE`` of the rows with backing on both
sides of them (``STREAK_MAX_MM`` away, in whole pixels rounded up) and over at least
``STREAK_MIN_MM`` of such rows, is not backing, is ``STREAK_LIGHTER`` levels brighter in every
channel than both of those two neighbours, and has the backing's tint (blue minus red) to within
``STREAK_TINT``. Its blurred edge, one pixel each side in the same rows, goes with it. Where
something crosses the streak, the pixels of the streak and its edge do not count as backing.
Synthetic arrays, numbers only.
"""

import math

import numpy as np
import pytest

from fastfoto_linux.documents.band import backing_distance
from fastfoto_linux.documents.guard import backing_pixels
from fastfoto_linux.documents.streak import (
    STREAK_LIGHTER,
    STREAK_MAX_MM,
    STREAK_MIN_MM,
    STREAK_SHARE,
    STREAK_TINT,
    _narrow_runs,
    crossed_pixels,
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
BACKING_TINT = int(BACKING[2] - BACKING[0])  # blue minus red of the backing: 17


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
    assert (STREAK_MAX_MM, STREAK_LIGHTER, STREAK_SHARE, STREAK_MIN_MM, STREAK_TINT) == (
        0.3,
        4.0,
        0.9,
        3.0,
        12.0,
    )


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


LEADS = {  # levels over the backing, per channel, with the one under test left out
    0: (None, 25, 14),
    1: (20, None, 20),
    2: (14, 25, None),
}  # each is 20 or more from the backing, and within 11 of its tint, whatever the low channel


@pytest.mark.parametrize("channel", [0, 1, 2])
@pytest.mark.parametrize(("lead", "is_streak"), [(5.0, True), (3.0, False)])
def test_a_line_must_be_a_few_levels_brighter_in_every_channel(
    channel: int, lead: float, is_streak: bool
) -> None:
    """The mean of the channels is far over the backing's in all of these; one channel is not."""
    rgb = plus(*(lead if level is None else level for level in LEADS[channel]))
    assert backing_distance(rgb[None, None])[0, 0] > 20
    assert found(streak_pixels(with_line(strip(), COLUMN, COLUMN + 2, rgb), DPI)) is is_streak


@pytest.mark.parametrize(
    ("shift", "is_streak"), [(0, True), (-12, True), (12, True), (-13, False), (13, False)]
)
def test_a_line_has_the_backings_tint_to_within_twelve(shift: int, is_streak: bool) -> None:
    """Blue minus red is 17 in the backing and 12 either side of that in a streak: all of these
    are 20 levels brighter or more in every channel."""
    rgb = plus(20, 25, 20 + shift)
    assert BACKING_TINT + shift == rgb[2] - rgb[0]
    assert found(streak_pixels(with_line(strip(), COLUMN, COLUMN + 2, rgb), DPI)) is is_streak


@pytest.mark.parametrize(
    "rgb",
    [(225, 225, 225), (238, 236, 225), (240, 215, 215), (255, 250, 190)],
    ids=["light-grey", "cream", "pink", "yellow"],
)
def test_a_pale_line_of_another_colour_is_not_a_streak(rgb: tuple[int, int, int]) -> None:
    assert not found(streak_pixels(with_line(strip(), COLUMN, COLUMN + 2, rgb), DPI))


@pytest.mark.parametrize("tone", [150, 100])
def test_a_dark_line_is_not_a_streak(tone: int) -> None:
    assert not found(streak_pixels(with_line(strip(), COLUMN, COLUMN + 2, tone), DPI))


def test_a_line_is_lighter_than_the_brighter_of_its_two_sides() -> None:
    """The right side is backing that is 10 levels brighter; the line is 20 over the left in
    every channel but only 3 over the right in green (and 7 on average)."""
    line = plus(20, 13, 20)
    assert found(streak_pixels(with_line(strip(), COLUMN, COLUMN + 1, line), DPI))
    image = with_line(strip(), COLUMN + OFFSET_PX, COLUMNS, plus(10, 10, 10))
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


@pytest.mark.parametrize(
    ("dpi", "is_streak"), [(100, False), (150, False), (169, False), (170, True), (200, True)]
)
def test_the_rule_is_off_where_two_pixels_are_wider_than_the_streak(
    dpi: int, is_streak: bool
) -> None:
    """A streak is a pixel or two wide: 2 pixels are 0.3 mm at 169.3 dpi, and below 170 dpi a
    pixel is too coarse to tell a streak from a line."""
    image = with_line(strip(), COLUMN, COLUMN + 2, LIGHT)
    assert found(streak_pixels(image, dpi)) is is_streak


@pytest.mark.parametrize(
    ("columns", "kept"),
    [
        ([0, 1, 1, 1, 0, 1, 1, 0], [0, 0, 0, 0, 0, 1, 1, 0]),
        ([1, 1, 1, 0, 0, 0, 1, 1], [0, 0, 0, 0, 0, 0, 1, 1]),
        ([0, 0, 1, 1, 1, 1, 1, 1], [0, 0, 0, 0, 0, 0, 0, 0]),
    ],
)
def test_a_run_of_streak_columns_wider_than_the_offset_is_not_a_streak(
    columns: list[int], kept: list[int]
) -> None:
    runs = np.asarray(columns, dtype=bool)
    assert _narrow_runs(runs, 2).tolist() == np.asarray(kept, dtype=bool).tolist()
    assert runs.tolist() == np.asarray(columns, dtype=bool).tolist()


@pytest.mark.parametrize("columns", [1, OFFSET_PX - 1, OFFSET_PX, 2 * OFFSET_PX])
def test_a_strip_with_no_room_for_backing_on_both_sides_has_no_streak(columns: int) -> None:
    narrow = np.tile(BACKING, (ROWS, columns, 1))
    mask = streak_pixels(narrow, DPI)
    assert mask.shape == narrow.shape[:2]
    assert not mask.any()


def test_the_backing_of_a_band_strip_needs_the_resolution_for_the_streak() -> None:
    with pytest.raises(ValueError, match="dpi"):
        backing_pixels(strip(), band=True)
    assert backing_pixels(with_line(strip(), COLUMN, COLUMN + 2, LIGHT), band=True, dpi=DPI).any()
    assert backing_pixels(strip()).all()


# ---- a mark crossing the streak ----------------------------------------------------------------

MARK_ROWS = slice(40, 43)


def crossed_strip() -> np.ndarray:
    """A streak two pixels wide, crossed in three rows by a grey stroke 20 pixels long: where
    the stroke lies over the streak, the blur with it is backing-coloured."""
    image = with_line(strip(), COLUMN, COLUMN + 2, LIGHT)
    image = with_line(image, COLUMN - 10, COLUMN + 10, 150, MARK_ROWS)
    return with_line(image, COLUMN, COLUMN + 2, BACKING, MARK_ROWS)


def test_a_streak_is_crossed_in_the_rows_where_its_neighbours_are_not_both_backing() -> None:
    """The stroke's rows, at the streak and the pixel each side of it that its blur reaches."""
    crossed = crossed_pixels(crossed_strip(), DPI)
    assert crossed[MARK_ROWS, COLUMN - 1 : COLUMN + 3].all()
    assert crossed.sum() == 3 * 4


def test_the_streak_found_is_still_the_streak_in_the_rows_that_are_clear() -> None:
    mask = streak_pixels(crossed_strip(), DPI)
    assert mask[:40, COLUMN].all()
    assert not mask[MARK_ROWS, COLUMN].any()


def test_the_pixels_of_a_crossed_streak_are_not_backing_whatever_their_colour() -> None:
    """A stroke over a light streak blurs into the backing's colour; it is part of the stroke."""
    backing = backing_pixels(crossed_strip(), band=True, dpi=DPI)
    assert not backing[MARK_ROWS, COLUMN : COLUMN + 2].any()
    assert backing[:40].all()


def test_a_faint_row_of_a_streak_with_backing_on_both_sides_is_not_crossed() -> None:
    """The streak is only 10 levels over the backing here, which is within 20: backing by
    colour, with backing beside it. Nothing crosses it."""
    image = with_line(strip(), COLUMN, COLUMN + 2, LIGHT)
    image = with_line(image, COLUMN, COLUMN + 2, plus(10, 10, 10), slice(10, 15))
    assert not crossed_pixels(image, DPI).any()
    assert backing_pixels(image, band=True, dpi=DPI).all()


@pytest.mark.parametrize("first", [5, COLUMN + 4], ids=["far-left", "touching-the-offset"])
def test_a_mark_that_does_not_lie_over_the_streak_does_not_cross_it(first: int) -> None:
    """Beside the streak, the mark is not backing and neither is the streak's own pixel: nothing
    of the streak is backing by colour in those rows, so nothing is to be taken away."""
    image = with_line(strip(), COLUMN, COLUMN + 2, LIGHT)
    image = with_line(image, first, first + 10, 150, MARK_ROWS)
    assert not crossed_pixels(image, DPI).any()


def test_a_strip_without_a_streak_has_nothing_crossed() -> None:
    image = with_line(strip(), 10, 40, 150, MARK_ROWS)
    assert not crossed_pixels(image, DPI).any()


@pytest.mark.parametrize("dpi", [100, 150])
def test_nothing_is_crossed_where_the_rule_is_off(dpi: int) -> None:
    assert not crossed_pixels(crossed_strip(), dpi).any()


def test_the_crossing_never_changes_its_input() -> None:
    image = crossed_strip()
    before = image.copy()
    crossed_pixels(image, DPI)
    assert np.array_equal(image, before)
