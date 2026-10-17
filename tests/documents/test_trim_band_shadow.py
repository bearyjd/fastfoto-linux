"""The band cut's last check judges backing with the band's own colour tolerance.

On real pages the band darkens towards the paper and rings next to the pad, so the strip that a
band cut removes holds tiny clusters of shadow tone: in the top rows of the strip, along a side
wedge's edge, and a speck of dust on the backing. Each is within the band's tolerance of the
backing colour (36) but not within the strict 20 of the last check, and each cancelled the cut.
Marks that are darker, not blue, or bigger than dust must still cancel it. Numbers only.
"""

import numpy as np
import pytest

from fastfoto_linux.documents.trim import trim_page
from tests.doc_synth import LETTER_MM, paper_scene, px, with_tinted_block
from tests.doc_synth_band import with_jpeg
from tests.documents.helpers import colour_page
from tests.documents.test_trim_band_real import assert_band_cut, frame, painted
from tests.documents.trim_helpers import DPI, RECEIPT_MM

SHADOW_TONE = (190, 197, 205)  # 22 from the backing, blue above red: inside 36, past 20
DUST_RGB = (191, 185, 186)  # a speck of dust on the backing
WEDGE_CLUSTERS_MM = [(0.17, 0.51), (0.34, 0.51)]  # across and along the wedge's edge
DUST_MM = (0.25, 0.34)
SPECK_COLUMNS_PX = (700, 1100, 1500, 1900)
TOP_ROWS_MM = 0.2  # the specks lie this far under the first row of the cut strip
MID_BAND_MM = 6.0
MARK_MM = 0.6  # at least 0.5 mm
# marks that are not backing and are at least 0.5 mm: darker, not blue, or beyond the tolerance
MARKS = {
    "neutral-grey": (150, 150, 150),
    "reddish-ink": (200, 140, 140),
    "dark-blue-ink": (70, 90, 160),
    "blue-grey-past-36": (170, 180, 190),
    "warm-grey": (214, 206, 192),  # 30 from the backing, but blue is not above red
}


def strip_top(scene) -> int:
    """The first row of the strip that the band cut removes, on the scene after the codec."""
    return scene.height - trim_page(colour_page(with_jpeg(scene))).bottom


def paint_at(scene, row: int, column: int, size_mm: tuple[float, float], value):
    """A cluster of ``size_mm`` (wide, tall) with its top left corner at (row, column)."""
    wide, tall = px(size_mm[0], scene.dpi), px(size_mm[1], scene.dpi)
    return painted(scene, slice(row, row + tall), slice(column, column + wide), value)


# ---- shadow-tone clusters are backing in a band cut --------------------------------------------


@pytest.mark.parametrize("tilt", [0.0, 1.5, -3.0])
@pytest.mark.parametrize("size_mm", [(0.3, 0.3), (0.8, 0.4), (1.4, 0.3)], ids=str)
def test_shadow_tone_specks_in_the_top_rows_of_the_cut_strip_do_not_keep_the_band(
    size_mm: tuple[float, float], tilt: float
) -> None:
    scene = frame(300, tilt_deg=tilt)
    row = strip_top(scene) + px(TOP_ROWS_MM, 300)
    for column in SPECK_COLUMNS_PX:
        scene = paint_at(scene, row, column, size_mm, SHADOW_TONE)
    scene = with_jpeg(scene)
    assert_band_cut(scene, trim_page(colour_page(scene)))


def wedge_edge(scene, row: int) -> tuple[int, int]:
    """The column where the side wedge of pad ends in ``row``, and 1 or -1 for the side it is on."""
    white = scene.image[row].min(axis=1) >= 250
    if white[0]:
        return int(np.argmin(white)), 1
    return scene.image.shape[1] - 1 - int(np.argmin(white[::-1])), -1


@pytest.mark.parametrize("tilt", [3.0, -3.0, 1.5])
@pytest.mark.parametrize("size_mm", WEDGE_CLUSTERS_MM, ids=str)
@pytest.mark.parametrize("where", ["top", "mid"])
def test_shadow_tone_along_the_edge_of_a_side_wedge_does_not_keep_the_band(
    tilt: float, size_mm: tuple[float, float], where: str
) -> None:
    scene = frame(300, tilt_deg=tilt)
    below = strip_top(scene) + px(TOP_ROWS_MM, 300) if where == "top" else None
    row = below or scene.paper_end + px(MID_BAND_MM, 300)
    edge, step = wedge_edge(scene, row)
    column = edge if step > 0 else edge - px(size_mm[0], 300) + 1
    scene = with_jpeg(paint_at(scene, row, column, size_mm, SHADOW_TONE))
    assert_band_cut(scene, trim_page(colour_page(scene)))


@pytest.mark.parametrize("dpi", [200, 300])
def test_a_speck_of_dust_on_the_backing_in_the_middle_of_the_band_does_not_keep_it(
    dpi: int,
) -> None:
    scene = frame(dpi, tilt_deg=1.5)
    scene = paint_at(scene, scene.paper_end + px(MID_BAND_MM, dpi), 1200, DUST_MM, DUST_RGB)
    scene = with_jpeg(scene)
    assert_band_cut(scene, trim_page(colour_page(scene)))


# ---- anything else still cancels the cut -------------------------------------------------------


@pytest.mark.parametrize("where", ["top", "mid"])
@pytest.mark.parametrize("name", list(MARKS))
def test_a_mark_of_half_a_millimetre_that_is_darker_or_not_blue_still_cancels_the_cut(
    name: str, where: str
) -> None:
    scene = frame(300, tilt_deg=1.5)
    row = strip_top(scene) + px(TOP_ROWS_MM, 300) if where == "top" else None
    row = row or scene.paper_end + px(MID_BAND_MM, 300)
    scene = with_jpeg(paint_at(scene, row, 1200, (MARK_MM, MARK_MM), MARKS[name]))
    assert not trim_page(colour_page(scene)).band_bottom


@pytest.mark.parametrize("name", list(MARKS))
def test_the_same_marks_at_200_dpi_still_cancel_the_cut(name: str) -> None:
    scene = frame(200, tilt_deg=-1.5)
    row = scene.paper_end + px(MID_BAND_MM, 200)
    scene = with_jpeg(paint_at(scene, row, 800, (MARK_MM, MARK_MM), MARKS[name]))
    assert not trim_page(colour_page(scene)).band_bottom


def test_the_same_shadow_tone_in_a_side_strip_is_not_backing_and_keeps_the_strip() -> None:
    """Only the band cut judges backing by the band's tolerance: a side strip, as before, keeps
    a note that is 22 from the backing colour."""
    scene = paper_scene(dpi=DPI, paper_mm=RECEIPT_MM, scan_mm=LETTER_MM, offset_mm=60.0)
    note = with_tinted_block(scene, -40.0, 100.0, (1.5, 1.5), SHADOW_TONE)
    result = trim_page(colour_page(note))
    assert result.left == 0
    assert result.right > 0
