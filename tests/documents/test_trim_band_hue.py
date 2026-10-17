"""The shadow of a band is forgiven only in the band's own hue; pale ink in the backing's
blue-grey is not the shadow.

The last check of a band cut forgives a speck of shadow tone (within 36 of the backing colour, not
within the strict 20) in the first 1.5 mm of the strip and at the pad's edge. A faded blue ink or a
pencil on a slip of the backing's colour is in that tone too, and its strokes are specks of
it. What tells them apart is the hue: on real pages the forgiven specks are blue over red by
0.3 to 19 levels (the backing 17, the shadow 14), a faded blue ink by 30 to 40. A speck is
forgiven only when its mean blue minus red is at most ``SHADOW_BLUE_MAX``. Numbers only.
"""

import pytest

from fastfoto_linux.documents.guard import SHADOW_BLUE_MAX
from fastfoto_linux.documents.trim import trim_page
from tests.doc_synth import BACKING_RGB, px
from tests.doc_synth_band import banded_scene, with_glyphs, with_jpeg
from tests.documents.helpers import colour_page
from tests.documents.test_trim_band_real import assert_band_cut, frame, painted
from tests.documents.test_trim_band_shadow import MID_BAND_MM, paint_at, strip_top

SLIP_RGB = (195, 205, 215)  # a slip in the backing's colour (10 from it)
INKS = {"blue": (175, 190, 215), "pencil": (185, 198, 215)}  # blue over red by 40 and 30
EDGE_RGB = {"forgiven": (188, 195, 210), "kept": (184, 192, 212)}  # blue over red by 22 and 28
FAR_DUST_RGB = (170, 178, 188)  # 55 from the backing, blue over red: not dust
DUST_SIZE_MM = (0.34, 0.34)
SHADOW_ROWS_MM = 0.2  # a speck of the gate's edge lies this far under the first row of the strip


def kept_rows(scene, result) -> int:
    return scene.height - result.bottom


# ---- ink on a slip of the backing's colour hanging below the paper is never cut ----------------


@pytest.mark.parametrize(
    ("ink", "dpi", "glyph_mm"), [("blue", 300, 2.5), ("pencil", 200, 1.2)], ids=str
)
@pytest.mark.parametrize("tilt", [0.0, 1.5])
def test_pale_ink_on_a_backing_coloured_slip_just_below_the_paper_is_kept(
    ink: str, dpi: int, glyph_mm: float, tilt: float
) -> None:
    """The strokes of the ink lie in the first millimetres of the strip, where the shadow's own
    specks are forgiven, and are specks themselves (0.4 mm wide): the hue tells them apart."""
    scene = frame(dpi, edge_line=True, tilt_deg=tilt)
    slip = slice(scene.paper_end - px(3.0, dpi), scene.paper_end + px(6.0, dpi))
    scene = painted(scene, slip, slice(scene.width // 8, 7 * scene.width // 8), SLIP_RGB)
    scene, bottom = with_glyphs(scene, scene.paper_end + px(1.5, dpi), glyph_mm, INKS[ink])
    scene = with_jpeg(scene)
    assert kept_rows(scene, trim_page(colour_page(scene))) >= bottom


# ---- ink in a bar of the backing's colour flush with the paper's end is never cut --------------


def bar_with_ink(dpi: int, tilt: float, bar_mm: float, glyph_mm: float, ink: str):
    """A page with a backing-coloured bar flush with the paper's end, no edge line and no shadow
    below it, and glyphs of pale ink on its last millimetres; the scene after the codec, and the
    row after the ink."""
    scene = frame(dpi, shadow_mm=0.0, edge_line=False, tilt_deg=tilt)
    bar = slice(scene.paper_end - px(bar_mm, dpi), scene.paper_end)
    scene = painted(scene, bar, slice(None), BACKING_RGB)
    top = scene.paper_end - px(0.6, dpi) - px(glyph_mm, dpi)
    scene, bottom = with_glyphs(scene, top, glyph_mm, INKS[ink])
    return with_jpeg(scene), bottom


@pytest.mark.parametrize("glyph_mm", [1.0, 1.5])
@pytest.mark.parametrize("tilt", [0.0, 1.5])
@pytest.mark.parametrize("dpi", [200, 300])
@pytest.mark.parametrize("ink", list(INKS))
def test_pale_ink_in_a_3_mm_bar_of_the_backing_colour_flush_with_the_paper_end_is_kept(
    ink: str, dpi: int, tilt: float, glyph_mm: float
) -> None:
    """No shadow lies below the bar, so the bar is cut with the band (a documented limit), but
    what is in it in another hue is not: the page stays whole to the ink's bottom."""
    scene, bottom = bar_with_ink(dpi, tilt, 3.0, glyph_mm, ink)
    assert kept_rows(scene, trim_page(colour_page(scene))) >= bottom


@pytest.mark.parametrize("tilt", [0.0, 1.5])
def test_pale_blue_ink_in_a_6_mm_bar_of_the_backing_colour_is_kept(tilt: float) -> None:
    scene, bottom = bar_with_ink(300, tilt, 6.0, 1.5, "blue")
    assert kept_rows(scene, trim_page(colour_page(scene))) >= bottom


# ---- the same at the top of the page ------------------------------------------------------------


@pytest.mark.parametrize("dpi", [200, 300])
@pytest.mark.parametrize("ink", list(INKS))
def test_pale_ink_in_a_backing_coloured_header_flush_with_the_page_top_is_not_cut(
    ink: str, dpi: int
) -> None:
    scene = banded_scene(dpi=dpi, top_mm=0.0, edge_line=False, paper_mm=60.0)
    scene = painted(scene, slice(0, px(3.5, dpi)), slice(None), BACKING_RGB)
    top = px(3.5, dpi) - px(0.6, dpi) - px(1.0, dpi)
    scene, _ = with_glyphs(scene, top, 1.0, INKS[ink])
    assert trim_page(colour_page(with_jpeg(scene))).top <= top


# ---- the gate sits between the shadow and the inks ---------------------------------------------


@pytest.mark.parametrize("dpi", [200, 300])
@pytest.mark.parametrize("name", list(EDGE_RGB))
def test_a_speck_is_forgiven_up_to_the_blue_over_red_of_the_gate_and_not_beyond(
    name: str, dpi: int
) -> None:
    """Specks 0.8 mm long under the first row of the strip, in tones 22 and 28 over red (the gate
    is between them), both inside the wide tolerance and outside the strict one."""
    rgb = EDGE_RGB[name]
    assert (rgb[2] - rgb[0] <= SHADOW_BLUE_MAX) is (name == "forgiven")
    scene = frame(dpi, tilt_deg=1.5)
    row = strip_top(scene) + px(SHADOW_ROWS_MM, dpi)
    for column in (700 * dpi // 300, 1100 * dpi // 300, 1500 * dpi // 300):
        scene = paint_at(scene, row, column, (0.8, 0.4), rgb)
    scene = with_jpeg(scene)
    result = trim_page(colour_page(scene))
    if name == "forgiven":
        assert_band_cut(scene, result)
    else:
        assert not result.band_bottom


# ---- dust is dust only near the backing colour --------------------------------------------------


@pytest.mark.parametrize("dpi", [200, 300])
def test_a_speck_of_dust_far_from_the_backing_colour_keeps_the_band(dpi: int) -> None:
    """Dust is under ``DUST_MM`` and within ``DUST_TOLERANCE`` of the backing colour, any hue; one
    at 55 from it (blue over red, so also past the gate's reach) is a mark."""
    scene = frame(dpi, tilt_deg=1.5)
    row = scene.paper_end + px(MID_BAND_MM, dpi)
    scene = with_jpeg(paint_at(scene, row, 1200 * dpi // 300, DUST_SIZE_MM, FAR_DUST_RGB))
    assert not trim_page(colour_page(scene)).band_bottom
