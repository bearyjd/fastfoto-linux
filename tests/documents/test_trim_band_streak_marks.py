"""A streak is forgiven for what it is: a mark that crosses it, or lies over it, is not.

The scanner's streak is a faint light vertical line down the backing band (see
``test_trim_band_streak``). What lies over or across it is ink, or a line of another colour, and
keeps the strip as it would without the streak; below 170 dpi a pixel is too coarse to tell a
streak from a line, and a blank slip of the backing's colour that touches the streak is cut with
the band, but one with anything on it is not. Numbers only: nothing here is a real pixel.
"""

import pytest

from fastfoto_linux.documents.trim import trim_page
from tests.doc_synth import px
from tests.doc_synth_band import with_jpeg
from tests.documents.helpers import colour_page
from tests.documents.test_trim_band_real import assert_band_cut, frame, painted
from tests.documents.test_trim_band_streak import (
    STREAK_RGB,
    backing_rows,
    band_rows,
    streak_column,
    streaked,
)

PINK_RGB = (240, 215, 215)
YELLOW_RGB = (255, 250, 190)
CREAM_RGB = (238, 236, 225)
LIGHT_GREY_RGB = (225, 225, 225)
PALE_BLUE_RGB = (175, 190, 215)
GREY_150_RGB = (150, 150, 150)
SLIP_RGB = (195, 205, 215)  # a backing-coloured slip
BLACK_RGB = (0, 0, 0)
FAINT_STREAK_RGB = (212, 220, 235)  # over the backing (202, 210, 219) by 10, 10 and 16
LINE_WIDTH_PX = 2


def kept(scene) -> bool:
    """Does the strip stay (the band is not cut)? The scene is coded as JPEG first."""
    return not trim_page(colour_page(with_jpeg(scene))).band_bottom


def streaky(dpi: int, tilt: float, width: int = LINE_WIDTH_PX):
    scene = frame(dpi, tilt_deg=tilt)
    return streaked(scene, streak_column(scene), width, STREAK_RGB)


def middle_rows(scene) -> tuple[int, int]:
    """The middle half of the rows of the band at the streak's column."""
    first, last = backing_rows(scene, streak_column(scene))
    span = last - first
    return first + span // 4, first + 3 * span // 4


# ---- a line of another colour over the streak ----------------------------------------------------


@pytest.mark.parametrize(
    "rgb",
    [PINK_RGB, YELLOW_RGB, CREAM_RGB, LIGHT_GREY_RGB],
    ids=["pink", "yellow", "cream", "light-grey"],
)
@pytest.mark.parametrize("tilt", [0.0, 1.5])
@pytest.mark.parametrize("dpi", [200, 300])
def test_a_line_of_another_colour_over_the_streak_keeps_the_band(
    dpi: int, tilt: float, rgb: tuple[int, int, int]
) -> None:
    """The line lies over the streak in the middle half of the band: it is lighter than the
    backing beside it, so that the column would be one streak from top to bottom; but it is not
    the backing's tint, and a streak must be."""
    scene = frame(dpi, tilt_deg=tilt)
    column = streak_column(scene)
    rows = middle_rows(scene)
    alone = streaked(scene, column, LINE_WIDTH_PX, rgb, rows)
    assert kept(alone)
    assert kept(streaked(streaked(scene, column, LINE_WIDTH_PX, STREAK_RGB), column, 2, rgb, rows))


# ---- a mark across the streak --------------------------------------------------------------------

STROKES = [
    ("pale-blue", PALE_BLUE_RGB, 2, [0.9, 1.1, 1.4]),
    ("grey-150", GREY_150_RGB, 1, [0.6, 0.75, 0.9]),
]


def stroked(scene, rgb, thickness: int, length_mm: float):
    """``scene`` with a horizontal stroke across the streak, in the middle of the band."""
    first, last = band_rows(scene)
    row = (first + last) // 2
    length = px(length_mm, scene.dpi)
    left = streak_column(scene) + 1 - length // 2
    return painted(scene, slice(row, row + thickness), slice(left, left + length), rgb)


@pytest.mark.parametrize(
    ("rgb", "thickness", "length_mm"),
    [(rgb, thick, mm) for _, rgb, thick, lengths in STROKES for mm in lengths],
    ids=[f"{name}-{mm}" for name, _, _, lengths in STROKES for mm in lengths],
)
@pytest.mark.parametrize("tilt", [0.0, 1.5])
@pytest.mark.parametrize("dpi", [200, 300])
def test_a_mark_across_the_streak_keeps_the_band_as_it_does_without_the_streak(
    dpi: int, tilt: float, rgb: tuple[int, int, int], thickness: int, length_mm: float
) -> None:
    """A stroke over the streak blurs into the backing's colour where it lies over the streak,
    and was cut into two dust-sized pieces."""
    scene = frame(dpi, tilt_deg=tilt)
    assert kept(stroked(scene, rgb, thickness, length_mm))
    assert kept(stroked(streaky(dpi, tilt), rgb, thickness, length_mm))


# ---- the faintest streak is still one ------------------------------------------------------------


@pytest.mark.parametrize("dpi", [200, 300, 600])
def test_the_faintest_streak_seen_on_a_real_page_is_still_forgiven(dpi: int) -> None:
    """10 levels over the backing in red and green and 16 in blue, two pixels wide: after the
    blur its lead is about 7 in every channel, over the 4 that a streak needs."""
    scene = frame(dpi, tilt_deg=0.0)
    faint = with_jpeg(streaked(scene, streak_column(scene), LINE_WIDTH_PX, FAINT_STREAK_RGB))
    assert_band_cut(faint, trim_page(colour_page(faint)))


# ---- low resolution: the rule is off -------------------------------------------------------------


@pytest.mark.parametrize("dpi", [100, 150])
def test_below_170_dpi_a_streak_keeps_the_band(dpi: int) -> None:
    """Two pixels are 0.3 mm at 169 dpi: a pixel or two of light line is not a streak below that
    (the rule is off) and keeps the strip, as before the rule. The same page without the streak
    is cut."""
    scene = frame(dpi, tilt_deg=0.0)
    clean = with_jpeg(scene)
    assert_band_cut(clean, trim_page(colour_page(clean)))
    assert kept(streaky(dpi, 0.0))


# ---- a slip of the backing's colour at the streak ------------------------------------------------

SLIP_MM = (20.0, 4.0)  # long and tall
DOT_PX = 4


def slip_at_streak(dpi: int, tilt: float):
    """A slip of the backing's colour just right of the streak, in the middle of the band."""
    scene = streaky(dpi, tilt)
    first, last = band_rows(scene)
    row = (first + last) // 2
    height = px(SLIP_MM[1], dpi)
    left = streak_column(scene) + LINE_WIDTH_PX
    rows, columns = (
        slice(row - height // 2, row + height // 2),
        slice(left, left + px(SLIP_MM[0], dpi)),
    )
    return painted(scene, rows, columns, SLIP_RGB), row, left


@pytest.mark.parametrize("tilt", [0.0, 1.5])
@pytest.mark.parametrize("dpi", [200, 300])
def test_a_blank_slip_of_the_backings_colour_touching_a_streak_goes_with_the_band(
    dpi: int, tilt: float
) -> None:
    """A documented limit: the slip joins the band by the streak, and a blank slip of the
    backing's colour is taken for the backing."""
    scene, _, _ = slip_at_streak(dpi, tilt)
    clean = with_jpeg(scene)
    assert_band_cut(clean, trim_page(colour_page(clean)))


@pytest.mark.parametrize("tilt", [0.0, 1.5])
@pytest.mark.parametrize("dpi", [200, 300])
def test_a_slip_with_anything_on_it_keeps_the_strip_though_it_touches_a_streak(
    dpi: int, tilt: float
) -> None:
    scene, row, left = slip_at_streak(dpi, tilt)
    middle = left + px(SLIP_MM[0], dpi) // 2
    dot = painted(scene, slice(row - 2, row + 2), slice(middle, middle + DOT_PX), BLACK_RGB)
    assert kept(dot)
