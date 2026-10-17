"""A separate island of the backing's colour in the white tail is not the band.

The last check of a band cut counts backing only where it is joined to a side of the strip or to
its first row, the band next to the cut. The pad used to bridge a backing-coloured island in the
white tail to the sides, so the island counted as backing and went with the tail: one of at least
5% of the width even moved the tail's start below itself. An island that touches the band's own
backing is taken for the band (a documented limit). Numbers only: nothing here is a real pixel.
"""

import pytest

from fastfoto_linux.documents.trim import _tail_start, trim_page
from tests.doc_synth import BACKING_RGB, px
from tests.doc_synth_band import with_jpeg
from tests.documents.helpers import colour_page
from tests.documents.test_trim_band_real import BAND_MM, assert_band_cut, frame, painted

SLIP_RGB = (195, 205, 215)
COLOURS = {"slip": SLIP_RGB, "backing": BACKING_RGB}
ISLAND_MM = (11.5, 3.0)  # wide and tall: over 5% of the width, so it moves the tail's start
FRAMES = [(200, 0.0), (200, 1.5), (300, 0.0)]  # resolution and tilt
SCRAP_MM = (6.0, 1.0)  # at a side, under 5% of the width: the tail's start stays where it is


def island_at(scene, offset_mm: float, size_mm: tuple[float, float], rgb, *, at_side=False):
    """``scene`` with an island of ``size_mm`` (wide, tall) ``offset_mm`` under the row where its
    tail starts (without the island), in the middle of the page or against its left edge, and the
    row after the island."""
    dpi = scene.dpi
    first = _tail_start(with_jpeg(scene).image, dpi) + px(offset_mm, dpi)
    column = 0 if at_side else int(0.45 * scene.width)
    wide, tall = px(size_mm[0], dpi), px(size_mm[1], dpi)
    painted_scene = painted(scene, slice(first, first + tall), slice(column, column + wide), rgb)
    return with_jpeg(painted_scene), first + tall


@pytest.mark.parametrize("offset_mm", [1.0, 5.0])
@pytest.mark.parametrize("name", list(COLOURS))
@pytest.mark.parametrize(("dpi", "tilt"), FRAMES)
def test_a_wide_island_of_the_backing_colour_in_the_white_tail_is_kept(
    dpi: int, tilt: float, name: str, offset_mm: float
) -> None:
    """The island is 5% of the width or more: the white around it is not the backing, and the pad
    must not join it to a side. The page stays to its bottom."""
    scene, bottom = island_at(frame(dpi, tilt_deg=tilt), offset_mm, ISLAND_MM, COLOURS[name])
    assert scene.height - trim_page(colour_page(scene)).bottom >= bottom


@pytest.mark.parametrize(("size_mm", "offset_mm"), [(1.0, 1.0), (3.0, 3.5)])
@pytest.mark.parametrize("name", list(COLOURS))
@pytest.mark.parametrize(("dpi", "tilt"), FRAMES[1:])
def test_a_small_island_of_the_backing_colour_in_the_white_tail_is_kept(
    dpi: int, tilt: float, name: str, size_mm: float, offset_mm: float
) -> None:
    scene, bottom = island_at(
        frame(dpi, tilt_deg=tilt), offset_mm, (size_mm, size_mm), COLOURS[name]
    )
    assert scene.height - trim_page(colour_page(scene)).bottom >= bottom


@pytest.mark.parametrize(("dpi", "tilt"), FRAMES[:2])
def test_a_scrap_of_the_backing_colour_at_a_side_in_the_first_3_mm_of_the_tail_is_cut(
    dpi: int, tilt: float
) -> None:
    """The first ``TAIL_KEEP_MM`` of the tail are in the strip, and a scrap that touches a side of
    it is joined to the side by backing alone: it is taken for the band (a documented limit)."""
    scene, bottom = island_at(frame(dpi, tilt_deg=tilt), 2.0, SCRAP_MM, BACKING_RGB, at_side=True)
    result = trim_page(colour_page(scene))
    assert result.band_bottom
    assert scene.height - result.bottom < bottom


@pytest.mark.parametrize(("dpi", "tilt"), FRAMES[:2])
def test_the_same_scrap_below_the_first_3_mm_of_the_tail_is_ink_and_kept(
    dpi: int, tilt: float
) -> None:
    """Beyond the strip only the ink search of the tail rule looks, and it finds the scrap."""
    scene, bottom = island_at(frame(dpi, tilt_deg=tilt), 4.0, SCRAP_MM, BACKING_RGB, at_side=True)
    assert scene.height - trim_page(colour_page(scene)).bottom >= bottom


@pytest.mark.parametrize("dpi", [200, 300])
def test_a_band_with_pad_at_both_sides_is_still_cut(dpi: int) -> None:
    """Pad (white) over 15% of the width at each end of the band's rows: the band's backing
    touches neither side, but it is the band next to the cut, the first row of the strip."""
    scene = frame(dpi, tilt_deg=0.0)
    rows = slice(scene.paper_end, scene.paper_end + px(BAND_MM, dpi))
    edge = int(0.15 * scene.width)
    scene = painted(scene, rows, slice(0, edge), 255)
    scene = with_jpeg(painted(scene, rows, slice(scene.width - edge, scene.width), 255))
    assert_band_cut(scene, trim_page(colour_page(scene)))
