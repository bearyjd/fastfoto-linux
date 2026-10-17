"""The limits of the band rule that a mutation check found nothing pinning: how far
from the top a band may start, the share of a row that must be non-white, where the pad's slant
ends and how many rows of the page are looked at. Numbers only: nothing here is a real pixel."""

import numpy as np
import pytest

from fastfoto_linux.documents.band import BOTTOM_EDGE, band_cut
from fastfoto_linux.documents.trim import trim_page
from fastfoto_linux.documents.units import mm_to_px
from tests.doc_synth import BACKING_RGB, px
from tests.doc_synth_band import banded_scene, with_jpeg
from tests.documents.helpers import colour_page
from tests.documents.test_trim_band_real import LEFTOVER_MM, assert_band_cut, frame, painted

WIDTH_PX = 400


@pytest.mark.parametrize("dpi", [200, 300])
def test_a_header_in_the_backing_colour_under_3_mm_of_white_at_the_top_is_not_a_band(
    dpi: int,
) -> None:
    """A band at the top lies within 0.5 mm of the page's edge; white above a backing-coloured
    header means it is part of the page."""
    scene = banded_scene(dpi=dpi, top_mm=0.0, edge_line=False, paper_mm=60.0)
    scene = with_jpeg(painted(scene, slice(px(3.0, dpi), px(6.0, dpi)), slice(None), BACKING_RGB))
    assert trim_page(colour_page(scene)).top == 0


@pytest.mark.parametrize("dpi", [200, 300])
def test_a_white_slip_over_half_the_width_in_the_band_is_not_band_rows(dpi: int) -> None:
    """Rows with white on 55% of their width are pad rows (a band row has non-white pixels on at
    least half): the band ends below the slip and the slip is kept."""
    scene = frame(dpi, tilt_deg=0.0)
    rows = slice(scene.paper_end, scene.paper_end + px(6.0, dpi))
    scene = with_jpeg(painted(scene, rows, slice(0, int(0.55 * scene.width)), 255))
    result = trim_page(colour_page(scene))
    assert result.band_bottom
    assert scene.height - result.bottom >= rows.stop


@pytest.mark.parametrize("dpi", [200, 300])
def test_a_white_slip_under_half_the_width_in_the_band_is_blank_and_goes_with_it(dpi: int) -> None:
    """The same slip over 45% of the width leaves 55% non-white: band rows, and a blank white
    slip that touches a side is no mark."""
    scene = frame(dpi, tilt_deg=0.0)
    rows = slice(scene.paper_end, scene.paper_end + px(6.0, dpi))
    scene = with_jpeg(painted(scene, rows, slice(0, int(0.45 * scene.width)), 255))
    assert_band_cut(scene, trim_page(colour_page(scene)))


@pytest.mark.parametrize("tilt", [3.0, -3.0, 1.5])
@pytest.mark.parametrize("band_mm", [35.0, 45.0])
def test_a_band_over_20_mm_is_not_cut_whatever_the_slant_of_the_pad(
    band_mm: float, tilt: float
) -> None:
    """The slant of the pad (11 mm at 3 degrees) is not part of the band: where it ends is found
    from the share of white, and a run longer than 20 mm from there is a header or a margin. Band
    sizes here are of the scanned rectangle: the full-width part is shorter by the slant."""
    scene = with_jpeg(frame(200, band_mm=band_mm, shadow_mm=0.0, tilt_deg=tilt))
    result = trim_page(colour_page(scene))
    assert not result.band_bottom
    assert scene.height - result.bottom >= scene.paper_end


@pytest.mark.parametrize("tilt", [3.0, -3.0])
def test_a_band_of_24_mm_scanned_is_cut_at_3_degrees_as_the_slant_is_not_counted(
    tilt: float,
) -> None:
    """24 mm from the middle of the pad's slant is 18 mm from where the slant ends (11 mm high at
    3 degrees): within the 20 mm of the rule, though the run from the middle is longer."""
    scene = with_jpeg(frame(200, band_mm=23.2, shadow_mm=0.8, tilt_deg=tilt))
    result = trim_page(colour_page(scene))
    kept = scene.height - result.bottom
    assert result.band_bottom
    assert scene.paper_end <= kept <= scene.paper_end + px(LEFTOVER_MM, 200)


def test_the_longest_band_that_starts_the_farthest_from_the_edge_is_found() -> None:
    """20 mm of pad, then a band of 20 mm: its end is the last row of the 40 mm looked at, and
    the paper above it must be in view for the end to be seen (300 dpi: 40 mm is 2 x 20 mm)."""
    dpi = 300
    row = np.full((1, WIDTH_PX, 3), np.asarray(BACKING_RGB, np.uint8), np.uint8)
    white = np.full((mm_to_px(30.0, dpi), WIDTH_PX, 3), 255, np.uint8)
    band = np.repeat(row, mm_to_px(BOTTOM_EDGE.max_mm, dpi), axis=0)
    pad = np.full((mm_to_px(BOTTOM_EDGE.reach_mm, dpi), WIDTH_PX, 3), 255, np.uint8)
    cut = band_cut(np.concatenate([white, band, pad]), dpi, BOTTOM_EDGE)
    keep = mm_to_px(BOTTOM_EDGE.keep_mm, dpi)
    assert cut == mm_to_px(BOTTOM_EDGE.reach_mm, dpi) + len(band) - keep
