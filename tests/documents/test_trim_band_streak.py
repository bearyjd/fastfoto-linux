"""A thin light streak down the backing band is the scanner's, not content.

A fleck on the scanner's glass or backing prints as a faint light vertical line down the band, 12
to 15 levels brighter than the backing, a pixel or two wide with its blur. It is not backing by
colour, so the last check of the band cut found something and cancelled the cut; where the line
splits the band, the far part, with a wedge of pad at its side and shadow along its first row,
joined nothing either. A light vertical line up to 0.3 mm wide down the whole band counts as
backing and joins the two parts. What is darker, wider, shorter or not in the band is still
content. Numbers only: nothing here is a real pixel.
"""

import math
from dataclasses import replace

import pytest

from fastfoto_linux.documents.trim import trim_page
from tests.doc_synth import LETTER_MM, paper_scene, px, with_tinted_block
from tests.doc_synth_band import SHADOW_RGB, banded_scene, with_jpeg
from tests.documents.helpers import colour_page
from tests.documents.test_trim_band_real import BAND_MM, assert_band_cut, frame, painted
from tests.documents.trim_helpers import DPI, RECEIPT_MM

STREAK_RGB = (224, 233, 246)  # 22 to 27 over the backing on every channel, blue over red
PAPER_STRIP_RGB = (236, 238, 237)  # paper that is not pad: every channel under 240
SLIP_RGB = (195, 205, 215)  # a backing-coloured slip
PALE_INK_RGB = (175, 190, 215)  # faded blue ink: 34 from the backing, darker
WHITE_MIN = 240
DPIS = (200, 300, 600)
TILTS = (0.0, 1.5, 3.0)
WIDTHS_PX = (2, 3)  # a pixel wide streak is within 20 of the backing once blurred: no trouble
STREAK_COLUMN = 0.45  # of the page width
SECOND_STREAK_MM = 1.6  # the real page had a second one this far from the first
PARTIAL_SHARE = 0.75  # of the band rows
WEDGE_SHARE = 0.15  # the pad's wedge at the far part's side, of the page width
SHADOW_ROW_MM = 0.4
GAP_PX = 3  # between the streak and the shadow row painted beside it


def band_rows(scene) -> tuple[int, int]:
    """First and last row (exclusive) of the shadow and the band in a ``scanner_page`` frame."""
    return scene.paper_end, scene.paper_end + px(BAND_MM, scene.dpi)


def strip_top(scene) -> int:
    """The first row of the strip the band cut removes (the scene is JPEG-coded first)."""
    return scene.height - trim_page(colour_page(with_jpeg(scene))).bottom


def streaked(scene, column: int, width: int, rgb, rows: tuple[int, int] | None = None):
    """``scene`` with a vertical line of ``width`` pixels at ``column`` over ``rows`` (the whole
    band by default). The pad stays: only the pixels that are not white take the colour."""
    first, last = rows or band_rows(scene)
    image = scene.image.copy()
    block = image[first:last, column : column + width]
    block[block.min(axis=2) < WHITE_MIN] = rgb
    return replace(scene, image=image)


def streak_column(scene) -> int:
    return int(STREAK_COLUMN * scene.width)


# ---- the streak does not keep the band ----------------------------------------------------------


@pytest.mark.parametrize("width", WIDTHS_PX)
@pytest.mark.parametrize("tilt", TILTS)
@pytest.mark.parametrize("dpi", DPIS)
def test_a_light_streak_down_the_whole_band_does_not_keep_it(
    dpi: int, tilt: float, width: int
) -> None:
    scene = frame(dpi, tilt_deg=tilt)
    scene = with_jpeg(streaked(scene, streak_column(scene), width, STREAK_RGB))
    assert_band_cut(scene, trim_page(colour_page(scene)))


@pytest.mark.parametrize("tilt", [0.0, 1.5])
@pytest.mark.parametrize("dpi", [200, 300])
def test_two_streaks_a_millimetre_and_a_half_apart_do_not_keep_the_band(
    dpi: int, tilt: float
) -> None:
    scene = frame(dpi, tilt_deg=tilt)
    first = streak_column(scene)
    scene = streaked(scene, first, 2, STREAK_RGB)
    scene = with_jpeg(streaked(scene, first + px(SECOND_STREAK_MM, dpi), 2, STREAK_RGB))
    assert_band_cut(scene, trim_page(colour_page(scene)))


def split_scene(dpi: int, tilt: float, width: int, *, streak: bool):
    """The streak splits the band; the part right of it has a wedge of pad at its side and a row
    of shadow tone along the first row of the strip, so that it joins nothing by itself."""
    scene = frame(dpi, tilt_deg=tilt)
    top, bottom = strip_top(scene), band_rows(scene)[1]
    column = streak_column(scene)
    if streak:
        scene = streaked(scene, column, width, STREAK_RGB)
    wedge = int(WEDGE_SHARE * scene.width)
    scene = painted(scene, slice(top, bottom), slice(scene.width - wedge, scene.width), 255)
    row = slice(top, top + px(SHADOW_ROW_MM, dpi))
    return with_jpeg(
        painted(scene, row, slice(column + width + GAP_PX, scene.width - wedge), SHADOW_RGB)
    )


@pytest.mark.parametrize("tilt", TILTS)
@pytest.mark.parametrize("dpi", DPIS)
def test_the_far_part_of_a_band_split_by_a_streak_is_not_content(dpi: int, tilt: float) -> None:
    """Pad at the far part's side and shadow along its top: only the streak joins it to the
    near part, which reaches the side of the strip."""
    scene = split_scene(dpi, tilt, 3, streak=True)
    assert_band_cut(scene, trim_page(colour_page(scene)))


@pytest.mark.parametrize("tilt", [0.0, 3.0])
@pytest.mark.parametrize("dpi", [200, 300])
def test_the_same_far_part_without_a_streak_is_joined_to_the_near_part_and_cut(
    dpi: int, tilt: float
) -> None:
    scene = split_scene(dpi, tilt, 3, streak=False)
    assert_band_cut(scene, trim_page(colour_page(scene)))


# ---- anything else down the band still keeps it -------------------------------------------------


@pytest.mark.parametrize("tone", [150, 100])
@pytest.mark.parametrize("tilt", [0.0, 1.5])
@pytest.mark.parametrize("dpi", DPIS)
def test_a_dark_streak_down_the_band_still_keeps_it(dpi: int, tilt: float, tone: int) -> None:
    """Ink darkens: only a lighter line can be forgiven. A dark streak is a documented limit."""
    scene = frame(dpi, tilt_deg=tilt)
    scene = with_jpeg(streaked(scene, streak_column(scene), 2, (tone, tone, tone)))
    assert not trim_page(colour_page(scene)).band_bottom


@pytest.mark.parametrize(
    ("width_mm", "rgb"),
    [(1.0, PAPER_STRIP_RGB), (1.0, STREAK_RGB), (0.7, STREAK_RGB)],
    ids=["paper-1mm", "streak-colour-1mm", "streak-colour-0.7mm"],
)
@pytest.mark.parametrize("tilt", [0.0, 1.5])
@pytest.mark.parametrize("dpi", DPIS)
def test_a_light_line_wider_than_a_streak_still_keeps_the_band(
    dpi: int, tilt: float, width_mm: float, rgb: tuple[int, int, int]
) -> None:
    scene = frame(dpi, tilt_deg=tilt)
    scene = with_jpeg(streaked(scene, streak_column(scene), px(width_mm, dpi), rgb))
    assert not trim_page(colour_page(scene)).band_bottom


@pytest.mark.parametrize("tilt", TILTS)
@pytest.mark.parametrize("dpi", DPIS)
def test_a_light_streak_over_part_of_the_band_rows_still_keeps_the_band(
    dpi: int, tilt: float
) -> None:
    """A streak is in 90% of the rows or more that have backing on both sides of it: this one
    stops after three quarters of the band's rows in the strip."""
    scene = frame(dpi, tilt_deg=tilt)
    column = streak_column(scene)
    first, last = strip_top(scene), band_rows(scene)[1]
    rows = [row for row in range(first, last) if scene.image[row, column].min() < WHITE_MIN]
    stop = first + round(PARTIAL_SHARE * len(rows))
    scene = with_jpeg(streaked(scene, column, 3, STREAK_RGB, (first, stop)))
    assert not trim_page(colour_page(scene)).band_bottom


@pytest.mark.parametrize("tilt", [0.0, 1.5])
@pytest.mark.parametrize("dpi", DPIS)
def test_a_pale_ink_stroke_darker_than_the_slip_it_lies_on_still_keeps_the_band(
    dpi: int, tilt: float
) -> None:
    """A slip of the backing's colour hangs in the band and a pale stroke of ink runs down it:
    the stroke is darker than the backing beside it, not lighter."""
    scene = frame(dpi, tilt_deg=tilt)
    first, last = band_rows(scene)
    width = scene.width
    scene = painted(scene, slice(first, last), slice(width // 4, 3 * width // 4), SLIP_RGB)
    scene = with_jpeg(streaked(scene, streak_column(scene), 2, PALE_INK_RGB))
    assert not trim_page(colour_page(scene)).band_bottom


def test_a_light_line_in_the_backing_beside_a_receipt_still_keeps_that_strip() -> None:
    """Only the strip of a band cut is judged for streaks: a side strip is not a band, and a line
    in it is no more forgiven than before."""
    scene = paper_scene(dpi=DPI, paper_mm=RECEIPT_MM, scan_mm=LETTER_MM, offset_mm=60.0)
    assert trim_page(colour_page(scene)).left > 0
    line = with_tinted_block(scene, -40.0, 0.0, (0.5, RECEIPT_MM[1]), STREAK_RGB)
    assert trim_page(colour_page(line)).left == 0


# ---- limits: a streak that leans, a streak in a short top band ---------------------------------

LEAN_DEG = 3.0  # the deskew moves the line across the band by 0.6 mm
TOP_BAND_MM = {"cut": 3.5, "kept": 2.0}  # the rule needs 3 mm of rows with backing on both sides


def leaning(scene, width: int, tilt_deg: float):
    """``scene`` with a line of ``width`` pixels down the band that moves ``tan(tilt_deg)``
    columns to the right for every row, the pad staying as it is."""
    first, last = band_rows(scene)
    start = streak_column(scene)
    image = scene.image.copy()
    for row in range(first, last):
        column = start + round((row - first) * math.tan(math.radians(tilt_deg)))
        block = image[row, column : column + width]
        block[block.min(axis=1) < WHITE_MIN] = STREAK_RGB
    return replace(scene, image=image)


@pytest.mark.parametrize("dpi", DPIS)
def test_a_streak_that_leans_across_the_band_is_not_found_and_keeps_the_band(dpi: int) -> None:
    scene = with_jpeg(leaning(frame(dpi, tilt_deg=0.0), 3, LEAN_DEG))
    assert not trim_page(colour_page(scene)).band_bottom


@pytest.mark.parametrize("dpi", DPIS)
def test_the_same_streak_standing_upright_is_found(dpi: int) -> None:
    scene = with_jpeg(leaning(frame(dpi, tilt_deg=0.0), 3, 0.0))
    assert_band_cut(scene, trim_page(colour_page(scene)))


@pytest.mark.parametrize("kind", list(TOP_BAND_MM))
@pytest.mark.parametrize("dpi", [200, 300])
def test_a_streak_in_the_top_band_is_forgiven_only_when_the_band_is_3_mm_or_more(
    dpi: int, kind: str
) -> None:
    top_mm = TOP_BAND_MM[kind]
    scene = banded_scene(dpi=dpi, top_mm=top_mm, edge_line=True, paper_mm=60.0)
    assert trim_page(colour_page(with_jpeg(scene))).top > 0
    streak = streaked(scene, streak_column(scene), 3, STREAK_RGB, (0, px(top_mm, dpi)))
    assert (trim_page(colour_page(with_jpeg(streak))).top > 0) is (kind == "cut")
