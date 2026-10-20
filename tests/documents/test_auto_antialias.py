"""Practical Auto B&W must tolerate text edges while retaining disconnected faint tones."""

import numpy as np
import pytest

from fastfoto_linux.documents.auto_colour import classify_colour
from fastfoto_linux.documents.encode import render_page
from fastfoto_linux.documents.modes import ColourMode
from tests.documents.auto_antialias import antialiased_page


@pytest.mark.parametrize("dpi", [300, 600])
@pytest.mark.parametrize("kind", [ColourMode.COLOUR, ColourMode.GREY])
def test_high_contrast_antialiased_text_on_noisy_light_paper_can_be_bilevel(
    dpi: int, kind: ColourMode
) -> None:
    page = antialiased_page(dpi, kind)
    original = page.pixels.copy()
    decision = classify_colour(page)
    assert decision.mode is ColourMode.BW
    rendered = render_page(page, decision.mode)
    grey = page.pixels[:, :, 0] if kind is ColourMode.COLOUR else page.pixels
    assert (rendered[grey < 96] == 0).all()
    assert (rendered[grey >= 240] == 255).all()
    assert np.array_equal(page.pixels, original)


@pytest.mark.parametrize("dpi", [300, 600])
@pytest.mark.parametrize("extra", ["pencil", "photo"])
def test_disconnected_faint_marks_and_photo_tones_are_preserved_beside_antialiased_text(
    dpi: int, extra: str
) -> None:
    page = antialiased_page(dpi, ColourMode.COLOUR, extra)
    assert classify_colour(page).mode is ColourMode.GREY
