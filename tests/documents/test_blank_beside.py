"""A faint line with another mark beside it is writing: pale type, tallies and "=" keep the page.

Light grey type that the scanner has blurred clears the detector's contrast only along the stems
of its letters. Each stem alone is a straight, thin, faint stroke, which is what a fold crease is,
and a page whose every mark was one was called blank. A crease has nothing beside it; writing has
other marks beside every stroke, and a mark with a neighbour is a mark.
"""

from typing import NamedTuple

import pytest

from fastfoto_linux.documents.blank import BLANK_MARGIN_MM, is_blank
from fastfoto_linux.documents.loader import LoadedPage
from fastfoto_linux.documents.marks import find_marks
from tests.doc_synth import Scene
from tests.doc_synth_creases import with_line
from tests.doc_synth_faint import softened, with_cursive_word, with_stem
from tests.doc_synth_text import pale_text_page, paragraph, with_serif_text
from tests.documents.blank_helpers import DPIS, KEPT, marks_of, sheet, verdicts
from tests.documents.helpers import colour_page

SERIF_PAPER_MM = (100.0, 40.0)
SERIF_TONES = [160, 170]
SERIF_BLURS_MM = [0.0, 0.1]
SERIF_MARKS = 90  # 3 rows of 30 letters


class Setting(NamedTuple):
    """How a page was set and scanned."""

    dpi: int
    points: int  # the type size
    darkest: int  # the darkest pixel
    blur_mm: float
    quality: int | None = None  # of the JPEG it was coded in, if it was


# Pages of the paragraph that were called blank although the plain detector finds dozens of marks.
PALE_PAGES = [
    Setting(200, 10, 190, 0.114),
    Setting(200, 12, 186, 0.178),
    Setting(200, 9, 186, 0.14, 85),
    Setting(200, 11, 186, 0.178, 85),
    Setting(300, 10, 190, 0.114),
    Setting(300, 10, 186, 0.14, 85),
    Setting(300, 11, 186, 0.178),
    Setting(600, 12, 186, 0.178),
]
MIN_PALE_MARKS = 40
FOOTERS = [
    ("Page 1 of 3   Confidential   generated 2026-10-17", Setting(200, 10, 190, 0.114, 85)),
    ("Page 1 of 3   Confidential   generated 2026-10-17", Setting(300, 8, 190, 0.09)),
    ("Acme Corp, 123 Main Street, Springfield", Setting(300, 8, 190, 0.09, 85)),
    ("www.example.com | 555-0100 | info@example.com", Setting(300, 8, 190, 0.09)),
    ("Invoice no. 2026-0417 - thank you for your business", Setting(300, 8, 190, 0.09)),
]
MIN_FOOTER_MARKS = 15
STRINGS = {"11": 170, "111": 170, "1 1": 170, "ii": 170, "Il": 170, "=": 150}
STRING_BLUR_MM = 0.114
STRING_PAGE_MM = (40.0, 30.0)
FOOTER_PAGE_MM = (110.0, 25.0)


def set_page(
    setting: Setting,
    lines: list[tuple[float, float, str]],
    size_mm: tuple[float, float] = (130.0, 40.0),
) -> LoadedPage:
    return pale_text_page(
        setting.dpi,
        lines,
        points=setting.points,
        darkest=setting.darkest,
        blur_mm=setting.blur_mm,
        size_mm=size_mm,
        jpeg_quality=setting.quality,
    )


def serif(dpi: int, tone: int, blur_mm: float) -> Scene:
    scene = with_serif_text(sheet(dpi, SERIF_PAPER_MM), 10.0, 10.0, 30, tone=tone, rows=3)
    return softened(scene, blur_mm=blur_mm, shadow_levels=0) if blur_mm else scene


# ---- pale type: only the stems register ------------------------------------------------------


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize("tone", SERIF_TONES)
@pytest.mark.parametrize("blur_mm", SERIF_BLURS_MM)
def test_the_pale_serif_page_is_a_mark_for_every_stem_to_the_plain_detector(
    dpi: int, tone: int, blur_mm: float
) -> None:
    assert len(marks_of(serif(dpi, tone, blur_mm))) == SERIF_MARKS


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize("tone", SERIF_TONES)
@pytest.mark.parametrize("blur_mm", SERIF_BLURS_MM)
def test_a_page_of_pale_serif_stems_keeps_the_page(dpi: int, tone: int, blur_mm: float) -> None:
    """Every stem has stems beside it: all of them are marks again."""
    scene = serif(dpi, tone, blur_mm)
    assert verdicts(scene) == KEPT
    kept = find_marks(colour_page(scene), margin_mm=BLANK_MARGIN_MM, ignore_faint_lines=True)
    assert len(kept) == SERIF_MARKS


@pytest.mark.parametrize("setting", PALE_PAGES)
def test_a_page_of_pale_blurred_type_keeps_the_page(setting: Setting) -> None:
    page = set_page(setting, paragraph(setting.points))
    assert len(find_marks(page, margin_mm=BLANK_MARGIN_MM)) >= MIN_PALE_MARKS
    assert not is_blank(page)


@pytest.mark.parametrize(("text", "setting"), FOOTERS)
def test_a_pale_footer_keeps_the_page(text: str, setting: Setting) -> None:
    page = set_page(setting, [(8.0, 10.0, text)], FOOTER_PAGE_MM)
    assert len(find_marks(page, margin_mm=BLANK_MARGIN_MM)) >= MIN_FOOTER_MARKS
    assert not is_blank(page)


# ---- a few strokes side by side --------------------------------------------------------------


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize("text", list(STRINGS))
def test_a_few_pale_strokes_side_by_side_keep_the_page(dpi: int, text: str) -> None:
    """Page numbers "11", "111", "ii", a tally mark "1 1", "Il", and an equals sign."""
    page = set_page(
        Setting(dpi, 10, STRINGS[text], STRING_BLUR_MM), [(15.0, 10.0, text)], STRING_PAGE_MM
    )
    assert len(find_marks(page, margin_mm=BLANK_MARGIN_MM)) >= 2
    assert not is_blank(page)


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize("count", [2, 4])
def test_a_tally_of_faint_strokes_keeps_the_page(dpi: int, count: int) -> None:
    scene = sheet(dpi)
    for number in range(count):
        scene = with_stem(scene, 40.0 + 1.5 * number, 50.0, 52.6, tone=160, stroke_mm=0.3)
    assert len(marks_of(scene)) == count
    assert verdicts(scene) == KEPT


@pytest.mark.parametrize("dpi", DPIS)
def test_an_equals_sign_of_two_faint_bars_keeps_the_page(dpi: int) -> None:
    scene = with_line(sheet(dpi), (40.0, 50.0), (43.0, 50.0), tone=160, thickness_mm=0.3)
    scene = with_line(scene, (40.0, 51.4), (43.0, 51.4), tone=160, thickness_mm=0.3)
    assert len(marks_of(scene)) == 2
    assert verdicts(scene) == KEPT


# ---- thin pen, blurred ------------------------------------------------------------------------


@pytest.mark.parametrize("pen_mm", [0.2, 0.3])
def test_a_blurred_thin_pen_cursive_word_that_breaks_into_straight_pieces_keeps_the_page(
    pen_mm: float,
) -> None:
    """Blur breaks the loops of a faint word into pieces that are each nearly straight."""
    scene = with_cursive_word(sheet(200, (100.0, 60.0)), 30.0, 25.0, tone=160, stroke_mm=pen_mm)
    scene = softened(scene, blur_mm=0.2, shadow_levels=0)
    assert len(marks_of(scene)) >= 5
    assert verdicts(scene) == KEPT
