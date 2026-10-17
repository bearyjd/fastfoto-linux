"""Faint writing is not a crease: a line is straight and thin, however faint and however long.

A flat cursive word and a pale highlighter band are as faint as a crease and many times longer
than wide, but the word is made of loops, never straight, and the band is 6 mm or more thick; a
crease is 0.2 to 0.5 mm thick and straight. (A signature wave, thin pens and a roman "ii" are in
``test_blank_strokes``.)
"""

import pytest

from fastfoto_linux.documents.blank import is_blank
from fastfoto_linux.documents.marks import STROKE_MAX_MM
from tests.doc_synth import Scene, with_tinted_block
from tests.doc_synth_faint import with_cursive_word, with_wave
from tests.documents.blank_helpers import (
    BLANK,
    DPIS,
    KEPT,
    bar,
    marks_of,
    sheet,
    verdicts,
)
from tests.documents.helpers import colour_page

WORD_MM = (100.0, 60.0)
BAND_PAPER_MM = (170.0, 60.0)
BANDS = [
    (80.0, 6.0, 140),
    (80.0, 6.0, 160),
    (80.0, 6.0, 180),
    (150.0, 12.0, 140),
    (150.0, 12.0, 150),
]
# A band 8 mm or taller is only a mark when it is 80 levels darker than the paper (blue 160 on
# paper at 240): the detector's page contrast. That is why the tall bands are not paler.
WAVE_AMPLITUDES_MM = [1.0, 2.5]
WORD_TONES = [150, 170]


def word(dpi: int, tone: int) -> Scene:
    return with_cursive_word(sheet(dpi, WORD_MM), 30.0, 25.0, tone=tone)


def band(dpi: int, size_mm: tuple[float, float], blue: int) -> Scene:
    """A pale yellow highlighter band: red and green stay high, the blue channel drops."""
    return with_tinted_block(sheet(dpi, BAND_PAPER_MM), 10.0, 20.0, size_mm, (255, 250, blue))


def wave(dpi: int, amplitude_mm: float) -> Scene:
    return with_wave(
        sheet(dpi, WORD_MM), 10.0, 30.0, tone=150, length_mm=75.0, amplitude_mm=amplitude_mm
    )


# ---- the fixtures are one mark to the plain detector, or the tests below prove nothing -------


@pytest.mark.parametrize("dpi", DPIS)
def test_the_cursive_word_is_one_mark_of_about_25_by_3_mm(dpi: int) -> None:
    (mark,) = marks_of(word(dpi, 150))
    width, height = ((mark.x1 - mark.x0) * 25.4 / dpi, (mark.y1 - mark.y0) * 25.4 / dpi)
    assert 23.0 < width < 28.0
    assert 2.6 <= height < 4.0


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize("size_mm", [(80.0, 6.0), (150.0, 12.0)])
def test_the_highlighter_band_is_one_mark_to_the_plain_detector(
    dpi: int, size_mm: tuple[float, float]
) -> None:
    assert len(marks_of(band(dpi, size_mm, 140))) == 1


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize("amplitude_mm", WAVE_AMPLITUDES_MM)
def test_the_wave_is_one_long_mark_to_the_plain_detector(dpi: int, amplitude_mm: float) -> None:
    (mark,) = marks_of(wave(dpi, amplitude_mm))
    assert (mark.x1 - mark.x0) * 25.4 / dpi > 70.0


# ---- faint writing keeps the page ------------------------------------------------------------


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize("tone", WORD_TONES)
def test_a_faint_flat_cursive_word_keeps_the_page(dpi: int, tone: int) -> None:
    assert verdicts(word(dpi, tone)) == KEPT


@pytest.mark.parametrize("dpi", DPIS)
def test_a_faint_cursive_word_flecked_with_darker_pencil_keeps_the_page(dpi: int) -> None:
    """Flecks as wide as the stroke (darkest 130, a millimetre apart) are the grain of the line,
    not dust: taking them off would leave the word too thin to count."""
    scene = with_cursive_word(sheet(dpi, WORD_MM), 30.0, 25.0, tone=150, grain_tone=130)
    assert len(marks_of(scene)) == 1
    assert verdicts(scene) == KEPT


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize(("width", "height", "blue"), BANDS)
def test_a_pale_highlighter_band_keeps_the_page(
    dpi: int, width: float, height: float, blue: int
) -> None:
    """Colour only: a grey page turns the yellow nearly white, so there is nothing to find."""
    assert not is_blank(colour_page(band(dpi, (width, height), blue)))


# ---- the edge of the stroke limit ------------------------------------------------------------


def test_a_faint_stroke_just_under_the_stroke_limit_is_a_line() -> None:
    assert verdicts(bar(300, STROKE_MAX_MM - 0.1, 20.0)) == BLANK


def test_a_faint_stroke_just_over_the_stroke_limit_counts_however_long() -> None:
    assert verdicts(bar(300, STROKE_MAX_MM + 0.1, 20.0)) == KEPT
