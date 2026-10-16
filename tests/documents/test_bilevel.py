"""Black and white: an adaptive threshold that follows the paper, not a fixed level."""

import numpy as np
import pytest

from fastfoto_linux.documents.bilevel import binarise
from tests.doc_synth import (
    PENCIL_TONE,
    Scene,
    paper_scene,
    to_grey,
    with_show_through,
    with_text,
    with_tinted_block,
)

INK_BELOW = 100
PAPER_ABOVE = 150


def text_page(dpi: int = 100, *, tone: int = 30) -> Scene:
    scene = paper_scene(dpi=dpi)
    for row in range(6):
        scene = with_text(scene, 25, 30 + row * 10, 25, tone=tone)
    return scene


def fractions(grey: np.ndarray, white: np.ndarray, *, ink: np.ndarray) -> tuple[float, float]:
    """(share of ink pixels that came out black, share of paper pixels that came out white)."""
    return float((~white[ink]).mean()), float(white[~ink].mean())


def test_ink_turns_black_and_paper_turns_white() -> None:
    grey = to_grey(text_page().image)
    white = binarise(grey, 100)
    assert white.dtype == np.bool_
    assert white.shape == grey.shape
    black_ink, white_paper = fractions(grey, white, ink=grey < INK_BELOW)
    assert black_ink > 0.95
    assert white_paper > 0.999


def test_a_light_pencil_note_still_turns_black() -> None:
    grey = to_grey(text_page(tone=PENCIL_TONE).image)
    black_ink, white_paper = fractions(grey, binarise(grey, 100), ink=grey < 200)
    assert black_ink > 0.9
    assert white_paper > 0.999


@pytest.mark.parametrize("dpi", [100, 300])
def test_uneven_lighting_does_not_turn_paper_black(dpi: int) -> None:
    grey = to_grey(text_page(dpi).image).astype(np.float32)
    shade = np.linspace(1.0, 0.72, grey.shape[1], dtype=np.float32)  # a third darker on one side
    grey = (grey * shade).astype(np.uint8)
    paper = grey > PAPER_ABOVE * 0.72
    white = binarise(grey, dpi)
    assert white[paper].mean() > 0.995
    assert (~white[grey < 90]).mean() > 0.9  # the ink is still found


def test_faint_show_through_stays_white() -> None:
    ghost = with_show_through(paper_scene(dpi=100, seed=2), text_page(), peak=20)
    grey = to_grey(ghost.image)
    assert grey.min() < 235
    assert binarise(grey, 100).mean() > 0.999


def test_the_input_is_not_modified() -> None:
    grey = to_grey(text_page().image)
    before = grey.copy()
    binarise(grey, 100)
    assert np.array_equal(grey, before)


# ---- solid dark areas are black, shading is not ink ------------------------------------------

BLOCK_MM = (40.0, 20.0)
BLOCK_AT_MM = (40.0, 60.0)
RING_MM = 3.0  # the outer band of a box, where an adaptive threshold would draw an outline
SHADING = 160
DARK_ENOUGH = 90  # below the absolute dark level: black wherever it is


def box_scene(tone: int, dpi: int) -> Scene:
    return with_tinted_block(paper_scene(dpi=dpi), *BLOCK_AT_MM, BLOCK_MM, (tone, tone, tone))


def black_share(white: np.ndarray, dpi: int, *, inset_mm: float = 0.0, ring: bool = False) -> float:
    """Share of black pixels in the block (``inset_mm`` smaller on every side), or in the
    ``RING_MM`` band along its edge."""
    x0, y0 = (round(v * dpi / 25.4) for v in BLOCK_AT_MM)
    width, height = (round(v * dpi / 25.4) for v in BLOCK_MM)
    cut = round((RING_MM if ring else inset_mm) * dpi / 25.4)
    mask = np.zeros(white.shape, bool)
    if ring:
        mask[y0 : y0 + height, x0 : x0 + width] = True
        mask[y0 + cut : y0 + height - cut, x0 + cut : x0 + width - cut] = False
    else:
        mask[y0 + cut : y0 + height - cut, x0 + cut : x0 + width - cut] = True
    return float((~white[mask]).mean())


@pytest.mark.parametrize("dpi", [100, 300])
@pytest.mark.parametrize("tone", [0, DARK_ENOUGH])
def test_a_big_solid_dark_block_is_black_all_the_way_through(dpi: int, tone: int) -> None:
    white = binarise(to_grey(box_scene(tone, dpi).image), dpi)
    assert black_share(white, dpi) >= 0.95


@pytest.mark.parametrize("dpi", [100, 300])
def test_shaded_grey_is_neither_outlined_nor_filled_black(dpi: int) -> None:
    """Decided: shading lighter than the dark level is background, so a box of it comes out
    white. A threshold that follows the local mean would draw a black outline round it."""
    white = binarise(to_grey(box_scene(SHADING, dpi).image), dpi)
    assert black_share(white, dpi, ring=True) <= 0.02
    assert black_share(white, dpi, inset_mm=RING_MM) <= 0.02


def test_text_inside_shading_stays_black_and_the_shading_stays_white() -> None:
    scene = with_text(box_scene(SHADING, 100), BLOCK_AT_MM[0] + 4, BLOCK_AT_MM[1] + 6, 12)
    grey = to_grey(scene.image)
    white = binarise(grey, 100)
    black_ink, _ = fractions(grey, white, ink=grey < INK_BELOW)
    assert black_ink > 0.9
    assert black_share(white, 100, ring=True) <= 0.02


def test_a_thin_mid_grey_rule_is_ink() -> None:
    scene = with_tinted_block(paper_scene(dpi=100), 20, 100, (150.0, 2.0), (SHADING,) * 3)
    grey = to_grey(scene.image)
    black_ink, _ = fractions(grey, binarise(grey, 100), ink=grey == SHADING)
    assert black_ink > 0.9


def test_a_wide_band_of_light_shading_stays_white() -> None:
    scene = with_tinted_block(paper_scene(dpi=100), 20, 100, (150.0, 6.0), (215,) * 3)
    grey = to_grey(scene.image)
    assert binarise(grey, 100).mean() > 0.995


# ---- the known limit: dark shading is solid black ---------------------------------------------

DARK_FILL = 80  # darker than the absolute dark level (96), lighter than the text on it
DARK_TEXT = 20


def test_black_text_on_a_dark_fill_is_lost_in_a_solid_black_area() -> None:
    """Documented (README, design doc): in black and white a fill darker than the dark level is
    black all the way through, so text printed on it in black cannot be read. Grey or colour
    keeps such a page."""
    scene = with_text(box_scene(DARK_FILL, 100), 44.0, 66.0, 12, tone=DARK_TEXT)
    white = binarise(to_grey(scene.image), 100)
    assert black_share(white, 100) >= 0.99


def test_light_text_on_a_dark_fill_stays_white_in_the_black_area() -> None:
    """A reversed heading is the use the dark rule exists for."""
    scene = with_text(box_scene(0, 100), 44.0, 66.0, 12, tone=255)
    grey = to_grey(scene.image)
    white = binarise(grey, 100)
    assert white[grey == 255].mean() > 0.9
