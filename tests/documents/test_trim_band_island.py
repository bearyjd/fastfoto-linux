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
from tests.documents.test_trim_band_real import frame, painted

SLIP_RGB = (195, 205, 215)
COLOURS = {"slip": SLIP_RGB, "backing": BACKING_RGB}
ISLAND_MM = (11.5, 3.0)  # wide and tall: over 5% of the width, so it moves the tail's start
FROM_BAND_MM = [1.0, 2.9, 5.0]  # from where the tail starts
SQUARES_MM = [1.0, 3.0]


def island_at(scene, offset_mm: float, size_mm: tuple[float, float], rgb):
    """``scene`` with an island of ``size_mm`` (wide, tall) ``offset_mm`` under the row where its
    tail starts (without the island), and the row after the island."""
    dpi = scene.dpi
    first = _tail_start(with_jpeg(scene).image, dpi) + px(offset_mm, dpi)
    column = int(0.45 * scene.width)
    wide, tall = px(size_mm[0], dpi), px(size_mm[1], dpi)
    painted_scene = painted(scene, slice(first, first + tall), slice(column, column + wide), rgb)
    return with_jpeg(painted_scene), first + tall


@pytest.mark.parametrize("offset_mm", FROM_BAND_MM)
@pytest.mark.parametrize("name", list(COLOURS))
@pytest.mark.parametrize("tilt", [0.0, 1.5])
@pytest.mark.parametrize("dpi", [200, 300])
def test_a_wide_island_of_the_backing_colour_in_the_white_tail_is_kept(
    dpi: int, tilt: float, name: str, offset_mm: float
) -> None:
    """The island is 5% of the width or more: the white around it is not the backing, and the pad
    must not join it to a side. The page stays to its bottom."""
    scene, bottom = island_at(frame(dpi, tilt_deg=tilt), offset_mm, ISLAND_MM, COLOURS[name])
    assert scene.height - trim_page(colour_page(scene)).bottom >= bottom


@pytest.mark.parametrize("offset_mm", [1.0, 3.5])
@pytest.mark.parametrize("size_mm", SQUARES_MM)
@pytest.mark.parametrize("name", list(COLOURS))
@pytest.mark.parametrize("tilt", [0.0, 1.5])
@pytest.mark.parametrize("dpi", [200, 300])
def test_a_small_island_of_the_backing_colour_in_the_white_tail_is_kept(
    dpi: int, tilt: float, name: str, size_mm: float, offset_mm: float
) -> None:
    scene, bottom = island_at(
        frame(dpi, tilt_deg=tilt), offset_mm, (size_mm, size_mm), COLOURS[name]
    )
    assert scene.height - trim_page(colour_page(scene)).bottom >= bottom
