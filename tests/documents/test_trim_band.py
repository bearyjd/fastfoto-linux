"""The scanner's backing band below (and above) the paper is cut, as measured on real pages.

From the bottom edge up: a pad of pure white over a slanted boundary, 6 to 15 mm of backing
across the whole width (darker next to the paper), an optional dark edge line of 1 mm, the paper
(often pure 255, like the pad). At the top 1 to 2 mm of backing, then the same edge line. The
cut is made below the edge line, never through it, and keeps at most a millimetre of the band.
"""

from dataclasses import replace

import numpy as np
import pytest

from fastfoto_linux.documents.trim import trim_page
from tests.doc_synth import (
    BACKING_RGB,
    EDGE_LINE_MM,
    Scene,
    banded_scene,
    px,
    with_text,
    with_tinted_block,
)
from tests.documents.helpers import bw_page, colour_page, grey_page

DPIS = (200, 300, 600)
KEEP_MM = 1.0
GLYPH_MM = 2.5
PALE_BACKING = (190, 200, 210)  # 18 from the backing colour, and 40 levels under the paper


def band_page(dpi: int, **kwargs) -> Scene:
    """600 dpi pages are small in millimetres so that each test stays fast."""
    small = {"width_mm": 90.0, "paper_mm": 40.0} if dpi >= 600 else {}
    return banded_scene(dpi=dpi, **{**small, **kwargs})


def kept_rows(scene: Scene, bottom: int, top: int = 0) -> np.ndarray:
    return scene.image[top : scene.height - bottom]


# ---- the bottom band ---------------------------------------------------------------------------


@pytest.mark.parametrize("edge_line", [True, False], ids=["edge-line", "no-edge-line"])
@pytest.mark.parametrize("band_mm", [6.0, 10.0, 15.0])
@pytest.mark.parametrize("dpi", DPIS)
def test_the_band_and_the_pad_below_the_paper_are_cut_keeping_a_millimetre(
    dpi: int, band_mm: float, edge_line: bool
) -> None:
    scene = band_page(dpi, band_mm=band_mm, edge_line=edge_line)
    result = trim_page(colour_page(scene))
    kept = scene.height - result.bottom
    assert result.band_bottom
    assert abs(kept - (scene.paper_end + px(KEEP_MM, dpi))) <= 1
    assert np.array_equal(result.page.pixels, scene.image[:kept])  # edge line and paper untouched
    assert (result.left, result.right, result.top) == (0, 0, 0)


@pytest.mark.parametrize("dpi", DPIS)
def test_paper_that_is_254_to_255_is_found_as_well_as_pure_255(dpi: int) -> None:
    scene = band_page(dpi, paper_noise=1)
    result = trim_page(colour_page(scene))
    assert abs(scene.height - result.bottom - (scene.paper_end + px(KEEP_MM, dpi))) <= 1


@pytest.mark.parametrize("dpi", DPIS)
def test_a_darker_shadow_next_to_the_paper_does_not_stop_the_cut(dpi: int) -> None:
    """The shadow's dark end is 27 from the backing colour, outside the tolerance of the last
    check; it is kept (with the edge line) instead of cancelling the cut."""
    scene = band_page(dpi, shadow_mm=2.5)
    result = trim_page(colour_page(scene))
    kept = scene.height - result.bottom
    assert result.band_bottom
    assert scene.paper_end + px(2.5, dpi) - 1 <= kept <= scene.paper_end + px(2.5, dpi) + 1


# ---- the top band ------------------------------------------------------------------------------


@pytest.mark.parametrize("edge_line", [True, False], ids=["edge-line", "no-edge-line"])
@pytest.mark.parametrize("top_mm", [1.0, 2.0])
@pytest.mark.parametrize("dpi", DPIS)
def test_the_backing_above_the_paper_is_cut_below_the_edge_line(
    dpi: int, top_mm: float, edge_line: bool
) -> None:
    scene = band_page(dpi, top_mm=top_mm, edge_line=edge_line)
    result = trim_page(colour_page(scene))
    assert result.top == scene.paper_top
    assert result.band_bottom
    kept = scene.height - result.bottom
    assert np.array_equal(result.page.pixels, scene.image[result.top : kept])


@pytest.mark.parametrize("dpi", DPIS)
def test_the_top_cut_needs_the_band_to_be_at_least_a_millimetre(dpi: int) -> None:
    scene = band_page(dpi, top_mm=0.5)
    assert trim_page(colour_page(scene)).top == 0


@pytest.mark.parametrize("dpi", DPIS)
def test_a_tall_backing_header_is_not_a_band(dpi: int) -> None:
    scene = band_page(dpi, top_mm=6.0)
    assert trim_page(colour_page(scene)).top == 0


# ---- content next to the band is kept ----------------------------------------------------------


@pytest.mark.parametrize("dpi", DPIS)
def test_a_footer_two_millimetres_above_the_edge_line_is_kept(dpi: int) -> None:
    scene = band_page(dpi)
    paper_mm = scene.paper_end / dpi * 25.4 - EDGE_LINE_MM
    scene = with_text(scene, 25, paper_mm - 2.0 - GLYPH_MM, 30)
    result = trim_page(colour_page(scene))
    assert result.band_bottom
    assert scene.content is not None
    assert scene.height - result.bottom >= scene.content[3] + px(2.0, dpi)


@pytest.mark.parametrize("dpi", DPIS)
def test_text_a_millimetre_under_the_top_edge_line_is_kept(dpi: int) -> None:
    scene = with_text(band_page(dpi, top_mm=2.0), 25, 1.0, 30)
    result = trim_page(colour_page(scene))
    assert result.top == scene.paper_top
    assert scene.content is not None
    assert result.top <= scene.content[1]


@pytest.mark.parametrize("dpi", DPIS)
def test_ink_in_the_band_cancels_the_cut_and_the_page_is_left_whole(dpi: int) -> None:
    scene = band_page(dpi)
    image = scene.image.copy()
    row = scene.paper_end + px(5.0, dpi)
    image[row : row + px(3.0, dpi), px(60.0, dpi) : px(63.0, dpi)] = 30  # a mark on the backing
    result = trim_page(colour_page(replace(scene, image=image)))
    assert (result.bottom, result.band_bottom) == (0, False)


# ---- the rule does not reach further than the band ---------------------------------------------


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize("band_mm", [1.0, 25.0], ids=["too-thin", "too-tall"])
def test_a_band_under_3_mm_or_over_20_mm_is_not_cut(dpi: int, band_mm: float) -> None:
    result = trim_page(colour_page(band_page(dpi, band_mm=band_mm)))
    assert (result.bottom, result.band_bottom) == (0, False)  # as before: nothing is cut


@pytest.mark.parametrize("dpi", DPIS)
def test_a_footer_bar_in_another_blue_grey_is_not_backing(dpi: int) -> None:
    scene = band_page(dpi, band_mm=3.0, shadow_mm=0.5, edge_line=False)
    image = scene.image.copy()
    rows = slice(scene.paper_end - px(5.0, dpi), scene.paper_end)
    image[rows] = (140, 160, 185)
    result = trim_page(colour_page(replace(scene, image=image)))
    assert scene.height - result.bottom >= scene.paper_end  # the bar stays whole


@pytest.mark.parametrize("dpi", DPIS)
def test_a_full_width_pale_bar_at_the_edge_is_the_known_limit(dpi: int) -> None:
    """A form margin printed edge to edge within the backing's tolerance (18 from it) cannot be
    told from the band: it is cut with it, as a full-height sidebar of that colour is at a side."""
    scene = band_page(dpi, band_mm=3.0, shadow_mm=0.0, edge_line=False)
    image = scene.image.copy()
    image[scene.paper_end - px(6.0, dpi) : scene.paper_end] = PALE_BACKING
    result = trim_page(colour_page(replace(scene, image=image)))
    assert result.band_bottom
    assert scene.height - result.bottom < scene.paper_end - px(4.0, dpi)


@pytest.mark.parametrize("dpi", DPIS)
def test_a_pale_form_margin_taller_than_the_band_cap_is_kept(dpi: int) -> None:
    scene = band_page(dpi, shadow_mm=0.0)
    image = scene.image.copy()
    image[scene.paper_end - px(25.0, dpi) : scene.paper_end] = PALE_BACKING
    result = trim_page(colour_page(replace(scene, image=image)))
    assert (result.bottom, result.band_bottom) == (0, False)  # as before: nothing is cut


@pytest.mark.parametrize("dpi", DPIS)
def test_the_band_does_not_change_what_is_cut_at_the_sides(dpi: int) -> None:
    plain = band_page(dpi, band_mm=3.0)  # a band under 3 mm: only the sides are in question
    scene = with_tinted_block(plain, 0, 0, (20.0, 40.0), PALE_BACKING)
    result = trim_page(colour_page(scene))
    assert (result.left, result.right) == (0, 0)  # as before: a margin only 40 mm tall stays


@pytest.mark.parametrize("dpi", DPIS)
def test_slanted_slivers_of_backing_at_the_sides_are_left(dpi: int) -> None:
    scene = band_page(dpi, band_mm=3.0)
    image = scene.image.copy()
    image[: scene.paper_end, : px(1.5, dpi)] = BACKING_RGB
    result = trim_page(colour_page(replace(scene, image=image)))
    assert (result.left, result.right) == (0, 0)


# ---- colour only, and the paper that must remain -----------------------------------------------


@pytest.mark.parametrize("make", [grey_page, bw_page], ids=["grey", "bw"])
def test_grey_and_bilevel_pages_are_not_cut_by_the_band_rule(make) -> None:
    scene = band_page(200, top_mm=1.5)
    result = trim_page(make(scene))
    assert (result.left, result.right, result.bottom, result.top) == (0, 0, 0, 0)
    assert not result.band_bottom


@pytest.mark.parametrize("dpi", DPIS)
def test_a_page_whose_paper_would_be_under_30_mm_is_not_cut(dpi: int) -> None:
    scene = band_page(dpi, paper_mm=22.0)  # the cut would leave about 26 mm
    result = trim_page(colour_page(scene))
    assert (result.bottom, result.top, result.band_bottom) == (0, 0, False)


@pytest.mark.parametrize("dpi", DPIS)
def test_the_30_mm_of_paper_stay_between_the_top_cut_and_the_bottom_cut_together(dpi: int) -> None:
    scene = band_page(dpi, paper_mm=26.0, top_mm=1.5)  # either cut alone leaves 30 mm or more
    result = trim_page(colour_page(scene))
    assert result.band_bottom
    assert result.top == 0
    assert result.page.pixels.shape[0] >= px(30.0, dpi)


@pytest.mark.parametrize("dpi", DPIS)
def test_a_narrow_item_on_the_backing_has_the_band_below_it_cut_and_nothing_beside_it(
    dpi: int,
) -> None:
    scene = band_page(dpi, paper_mm=60.0)
    image = scene.image.copy()
    image[: scene.paper_end, : px(25.0, dpi)] = BACKING_RGB  # the sheet is a 65 mm slip
    image[: scene.paper_end, px(25.0 + 65.0, dpi) :] = BACKING_RGB
    result = trim_page(colour_page(replace(scene, image=image)))
    kept = scene.height - result.bottom
    assert result.band_bottom
    assert abs(kept - (scene.paper_end + px(KEEP_MM, dpi))) <= 1


@pytest.mark.parametrize("dpi", [200, 300])
def test_a_slip_14_mm_wide_on_the_backing_is_not_a_band_row(dpi: int) -> None:
    """Its rows are 93% backing: 5% of the width is the most a band row may hold."""
    scene = band_page(dpi, paper_mm=60.0)
    image = scene.image.copy()
    image[: scene.paper_end, : px(100.0, dpi)] = BACKING_RGB
    image[: scene.paper_end, px(114.0, dpi) :] = BACKING_RGB
    result = trim_page(colour_page(replace(scene, image=image)))
    assert result.band_bottom
    assert abs(scene.height - result.bottom - (scene.paper_end + px(KEEP_MM, dpi))) <= 1


@pytest.mark.parametrize("dpi", [200, 300])
def test_a_mark_in_the_pad_means_it_is_not_pad_and_nothing_is_cut(dpi: int) -> None:
    scene = band_page(dpi)
    image = scene.image.copy()
    image[-px(6.0, dpi) : -px(4.0, dpi), px(20.0, dpi) : px(30.0, dpi)] = 30  # a black rectangle
    result = trim_page(colour_page(replace(scene, image=image)))
    assert (result.bottom, result.band_bottom) == (0, False)


@pytest.mark.parametrize("dpi", [200, 300])
def test_a_band_more_than_20_mm_from_the_bottom_edge_is_not_looked_for(dpi: int) -> None:
    scene = band_page(dpi)
    white = np.full((px(30.0, dpi), scene.width, 3), 255, np.uint8)
    deep = replace(scene, image=np.concatenate([scene.image, white]))
    result = trim_page(colour_page(deep))
    assert not result.band_bottom  # the white tail rule decides, as before


@pytest.mark.parametrize("dpi", [200, 300])
def test_dust_in_the_pad_does_not_stop_the_cut(dpi: int) -> None:
    scene = band_page(dpi)
    image = scene.image.copy()
    for number, row in enumerate(range(px(1.0, dpi), px(8.0, dpi), px(1.5, dpi))):
        column = px(20.0 + 15.0 * number, dpi)
        image[-row - 3 : -row, column : column + 3] = 120  # a speck of three pixels
    result = trim_page(colour_page(replace(scene, image=image)))
    assert result.band_bottom


@pytest.mark.parametrize("dpi", [200, 300])
def test_a_band_cut_that_is_cancelled_leaves_the_white_tail_rule_to_decide(dpi: int) -> None:
    scene = band_page(dpi)
    white = np.full((px(8.0, dpi), scene.width, 3), 255, np.uint8)
    image = np.concatenate([scene.image, white])
    row = scene.paper_end + px(5.0, dpi)
    image[row : row + px(3.0, dpi), px(60.0, dpi) : px(63.0, dpi)] = 30  # a mark on the backing
    result = trim_page(colour_page(replace(scene, image=image)))
    assert not result.band_bottom
    assert 0 < result.bottom <= px(8.0, dpi)  # only the white tail goes, as before


def with_mark(scene: Scene, row: int, column: int, *, size_px: int) -> Scene:
    image = scene.image.copy()
    image[row : row + size_px, column : column + size_px] = 30
    return replace(scene, image=image)


@pytest.mark.parametrize("dpi", [200, 300])
def test_a_white_slip_in_the_band_with_a_mark_on_it_cancels_the_cut(dpi: int) -> None:
    """Pure white in the band is not the pad: the last check still looks at the slip's rows."""
    scene = band_page(dpi)
    image = scene.image.copy()
    row, column = scene.paper_end + px(3.0, dpi), px(60.0, dpi)
    image[row : row + px(6.0, dpi), column : column + px(10.0, dpi)] = 255  # 4.6% of the width
    marked = with_mark(
        replace(scene, image=image), row + px(1.5, dpi), column + px(3.0, dpi), size_px=px(3.0, dpi)
    )
    result = trim_page(colour_page(marked))
    assert (result.bottom, result.band_bottom) == (0, False)
    assert trim_page(colour_page(replace(scene, image=image))).band_bottom  # blank, it goes


@pytest.mark.parametrize("dpi", [200, 300])
def test_white_next_to_the_paper_does_not_switch_the_last_check_off(dpi: int) -> None:
    """A slightly tilted paper edge leaves a few percent of white in the first band rows."""
    scene = band_page(dpi)
    image = scene.image.copy()
    row = scene.paper_end + px(0.8, dpi)
    image[row : row + 2, : round(scene.width * 0.03)] = 255
    tilted = replace(scene, image=image)
    assert trim_page(colour_page(tilted)).band_bottom
    marked = with_mark(tilted, scene.paper_end + px(5.0, dpi), px(60.0, dpi), size_px=px(3.0, dpi))
    result = trim_page(colour_page(marked))
    assert (result.bottom, result.band_bottom) == (0, False)


@pytest.mark.parametrize("dpi", [200, 300])
def test_a_band_with_white_in_every_row_is_not_trusted(dpi: int) -> None:
    """A white line down the whole band: no row without white to tell the pad from the rest."""
    scene = band_page(dpi)
    image = scene.image.copy()
    image[scene.paper_end :, px(60.0, dpi) : px(60.0, dpi) + 3] = 255
    result = trim_page(colour_page(replace(scene, image=image)))
    assert (result.bottom, result.band_bottom) == (0, False)
