"""Black and white: an adaptive threshold that follows the paper, not a fixed level."""

import numpy as np
import pytest

from fastfoto_linux.documents.bilevel import binarise
from tests.doc_synth import PENCIL_TONE, Scene, paper_scene, to_grey, with_show_through, with_text

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
