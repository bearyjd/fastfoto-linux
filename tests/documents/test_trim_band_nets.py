"""The band cut's last check must not take pale content for the shadow.

Judging backing in a band cut by the band's own tolerance (36) everywhere would make anything
blue-grey within 36 of the backing colour "backing", to go with the band: a bar printed
flush with the paper's end, pale ink on a backing-coloured slip, a pale island in the tail. The
wide tolerance is only for where the real shadow is: the top of the cut strip, next to the kept
band, and the edge of the pad. Elsewhere the strict 20 judges. Numbers only: no real pixel.
"""

import pytest

from fastfoto_linux.documents.trim import trim_page
from tests.doc_synth import BACKING_RGB, px
from tests.doc_synth_band import banded_scene, with_jpeg
from tests.documents.helpers import colour_page
from tests.documents.test_trim_band_real import BAND_MM, PALE_BACKING, frame, painted
from tests.documents.test_trim_band_shadow import (
    MID_BAND_MM,
    SHADOW_TONE,
    paint_at,
    wedge_edge,
)

STEEL = (176, 196, 222)  # 30 from the backing colour: past the strict 20, inside the band's 36
PASTEL = (200, 220, 240)  # 23 from it
SLIP_RGB = (195, 205, 215)  # a backing-coloured slip
PALE_INKS = {"blue": (175, 190, 215), "pencil": (185, 198, 215)}  # 34 and 21 from the backing
DPIS = (200, 300, 600)
TILTS = (0.0, 1.5)
# bar height (mm), inset from each side (mm, white beside the bar), colour
BARS = [(6.0, 0.0, STEEL), (10.0, 12.0, PASTEL), (6.0, 12.0, PASTEL), (10.0, 0.0, STEEL)]
ISLANDS = [(3.0, SLIP_RGB), (6.0, (202, 210, 219))]  # size (mm) and colour of an island in the tail


def kept_rows(scene, result) -> int:
    return scene.height - result.bottom


# ---- a bar flush with the paper's end, in a blue-grey near the backing, is never cut into ------


@pytest.mark.parametrize(("bar_mm", "inset_mm", "rgb"), BARS, ids=str)
@pytest.mark.parametrize("tilt", TILTS)
@pytest.mark.parametrize("dpi", DPIS)
def test_a_pale_bar_flush_with_the_paper_end_is_not_cut_into(
    dpi: int, tilt: float, bar_mm: float, inset_mm: float, rgb: tuple[int, int, int]
) -> None:
    """No gap and no edge line between the bar and the band: only the colour tells them apart.
    The wide tolerance of the last check must not cut 2 to 6 mm of it."""
    scene = frame(dpi, edge_line=False, tilt_deg=tilt)
    bar = slice(scene.paper_end - px(bar_mm, dpi), scene.paper_end)
    sides = slice(px(inset_mm, dpi), scene.width - px(inset_mm, dpi))
    scene = with_jpeg(painted(scene, bar, sides, rgb))
    assert kept_rows(scene, trim_page(colour_page(scene))) >= scene.paper_end


@pytest.mark.parametrize("bar_mm", [6.0, 10.0])
@pytest.mark.parametrize("tilt", TILTS)
@pytest.mark.parametrize("dpi", [200, 300])
def test_a_bar_in_the_backing_colour_flush_with_the_paper_end_is_kept_when_a_shadow_lies_below(
    dpi: int, tilt: float, bar_mm: float
) -> None:
    """The known limit is a bar that is the backing's own colour. The band's shadow (27 from the
    backing) lies below the bar, far from the cut, so the last check does not forgive it: the
    bar stays. Without a shadow (``shadow_mm=0``) the bar is cut with the band, as documented."""
    scene = frame(dpi, edge_line=False, tilt_deg=tilt)
    bar = slice(scene.paper_end - px(bar_mm, dpi), scene.paper_end)
    scene = with_jpeg(painted(scene, bar, slice(None), BACKING_RGB))
    assert kept_rows(scene, trim_page(colour_page(scene))) >= scene.paper_end


@pytest.mark.parametrize(("share", "cut"), [(1.0, True), (0.55, True), (0.45, False)])
@pytest.mark.parametrize("dpi", [200, 300])
def test_a_bar_within_20_of_the_backing_and_no_shadow_below_it_is_cut_if_half_the_page_wide(
    dpi: int, share: float, cut: bool
) -> None:
    """The documented limit: with no darker shadow in the way, such a bar cannot be told from the
    band. Under half the width its rows are mostly white (pad rows): the band ends below it."""
    scene = frame(dpi, band_mm=3.0, shadow_mm=0.0, edge_line=False, tilt_deg=1.5)
    inset = round((1.0 - share) / 2 * scene.width)
    bar = slice(scene.paper_end - px(6.0, dpi), scene.paper_end)
    scene = with_jpeg(painted(scene, bar, slice(inset, scene.width - inset), PALE_BACKING))
    result = trim_page(colour_page(scene))
    assert (kept_rows(scene, result) < scene.paper_end - px(4.0, dpi)) is cut


# ---- pale ink on a backing-coloured slip below the paper is never cut --------------------------


@pytest.mark.parametrize("ink", list(PALE_INKS))
@pytest.mark.parametrize("hang_mm", [4.0, 8.0])
@pytest.mark.parametrize("tilt", TILTS)
@pytest.mark.parametrize("dpi", DPIS)
def test_pale_ink_on_a_backing_coloured_slip_hanging_below_the_paper_is_kept(
    dpi: int, tilt: float, hang_mm: float, ink: str
) -> None:
    """The slip is as pale as the backing; the ink is past the strict tolerance, inside 36. At
    4 mm it lies within the first millimetre of the strip, where the shadow's own specks are
    forgiven: a 10 mm stroke is longer than any of them."""
    scene = frame(dpi, edge_line=True, tilt_deg=tilt)
    width = scene.width
    bottom = scene.paper_end + px(hang_mm, dpi)
    slip = slice(scene.paper_end - px(3.0, dpi), bottom)
    scene = painted(scene, slip, slice(width // 4, 3 * width // 4), SLIP_RGB)
    rows = slice(bottom - px(3.5, dpi), bottom - px(2.0, dpi))
    first = int(0.45 * width)
    scene = with_jpeg(painted(scene, rows, slice(first, first + px(10.0, dpi)), PALE_INKS[ink]))
    assert kept_rows(scene, trim_page(colour_page(scene))) >= rows.stop


# ---- a top header bar flush with the page top is not cut ---------------------------------------


@pytest.mark.parametrize("rgb", [STEEL, PASTEL], ids=["steel", "pastel"])
@pytest.mark.parametrize("bar_mm", [2.0, 3.5])
@pytest.mark.parametrize("dpi", [200, 300])
def test_a_pale_header_bar_flush_with_the_page_top_is_not_cut(
    dpi: int, bar_mm: float, rgb: tuple[int, int, int]
) -> None:
    scene = banded_scene(dpi=dpi, top_mm=0.0, edge_line=False, paper_mm=60.0)
    scene = with_jpeg(painted(scene, slice(0, px(bar_mm, dpi)), slice(None), rgb))
    assert trim_page(colour_page(scene)).top == 0


@pytest.mark.parametrize(
    ("row_mm", "forgiven"), [(1.6, True), (0.4, False)], ids=["next-to-cut", "far"]
)
@pytest.mark.parametrize("dpi", [200, 300])
def test_at_the_top_the_shadow_is_forgiven_next_to_the_cut_and_not_at_the_edge_of_the_page(
    dpi: int, row_mm: float, forgiven: bool
) -> None:
    """The strip of a top cut runs from the page's edge to the cut: its 1.5 mm that count as the
    top of the strip are the ones at the paper, not the ones at the edge of the page."""
    scene = banded_scene(dpi=dpi, top_mm=3.0, edge_line=True, paper_mm=60.0)
    first = px(row_mm, dpi)
    speck = painted(
        scene,
        slice(first, first + px(0.4, dpi)),
        slice(px(100.0, dpi), px(101.2, dpi)),
        SHADOW_TONE,
    )
    assert (trim_page(colour_page(with_jpeg(speck))).top > 0) is forgiven


@pytest.mark.parametrize("tilt", [-3.0, 1.5])
def test_shadow_tone_a_pixel_off_the_edge_of_a_side_wedge_is_forgiven_up_to_2_mm_long(
    tilt: float,
) -> None:
    """Dust is under 0.5 mm: a run of 0.9 mm in the shadow's tone by the wedge's edge is the
    shadow's fringe, which the pad's edge zone forgives (it is shorter than 2 mm)."""
    scene = frame(300, tilt_deg=tilt)
    row = scene.paper_end + px(MID_BAND_MM, 300)
    edge, step = wedge_edge(scene, row)
    size = (0.34, 0.9)
    column = edge + 1 if step > 0 else edge - 1 - px(size[0], 300) + 1
    scene = with_jpeg(paint_at(scene, row, column, size, SHADOW_TONE))
    assert trim_page(colour_page(scene)).band_bottom


# ---- backing is joined to a side through the pad of the band, not through the white tail -------


@pytest.mark.parametrize(("size_mm", "rgb"), ISLANDS, ids=str)
@pytest.mark.parametrize("offset_mm", [30.0, 60.0])
@pytest.mark.parametrize("dpi", [200, 300])
def test_a_pale_island_in_the_white_tail_is_not_cut_as_the_tail_rule_keeps_it(
    dpi: int, offset_mm: float, size_mm: float, rgb: tuple[int, int, int]
) -> None:
    """The white of the tail would join the island to both sides, to be taken for backing and
    cut. Ink in the tail is found as the tail rule finds it (origin/main keeps it as well)."""
    scene = frame(dpi, tilt_deg=1.5)
    first = scene.paper_end + px(BAND_MM + offset_mm, dpi)
    column = int(0.45 * scene.width)
    size = px(size_mm, dpi)
    scene = with_jpeg(painted(scene, slice(first, first + size), slice(column, column + size), rgb))
    assert kept_rows(scene, trim_page(colour_page(scene))) >= first + size
