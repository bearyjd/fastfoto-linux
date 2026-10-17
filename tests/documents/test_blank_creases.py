"""Fold creases do not keep a blank page; writing does, however faint, unless it is a thin line.

The rule: a mark does not count toward "not blank" when it is line-like (0.6 mm thick or less, or
8 times longer than wide) and faint (its darkest pixel is 140 or lighter). Everything else counts.
"""

import numpy as np
import pytest

from fastfoto_linux.documents.blank import BLANK_MARGIN_MM, is_blank
from fastfoto_linux.documents.marks import (
    FAINT_DARKEST,
    LINE_ASPECT,
    LINE_MAX_MM,
    find_marks,
)
from tests.doc_synth import (
    INK_TONE,
    SPECK_TONE,
    Scene,
    paper_scene,
    with_show_through,
    with_solid_block,
    with_specks,
    with_text,
)
from tests.doc_synth_creases import (
    with_creases,
    with_line,
    with_pencil_words,
    with_slanted_artefact,
)
from tests.documents.helpers import colour_page, grey_page, pages_of

DPIS = [200, 300, 600]
KINDS = ["colour", "grey", "bw"]
BLANK = dict.fromkeys(KINDS, True)
KEPT = dict.fromkeys(KINDS, False)
SMALL_MM = (100.0, 120.0)  # creases at 40 and 80 mm; small so that 600 dpi stays fast
TALL_MM = (100.0, 230.0)  # tall enough for a 153 mm artefact
FAINT_BAR_TONE = 160


def sheet(dpi: int, paper_mm: tuple[float, float] = SMALL_MM, **kwargs) -> Scene:
    return paper_scene(dpi=dpi, paper_mm=paper_mm, **kwargs)


def verdicts(scene: Scene) -> dict[str, bool]:
    return {kind: is_blank(page) for kind, page in pages_of(scene).items()}


def grey_verdicts(scene: Scene) -> dict[str, bool]:
    """For tones a 1-bit page turns white (lighter than 128): colour and grey only."""
    return {"colour": is_blank(colour_page(scene)), "grey": is_blank(grey_page(scene))}


def bar(dpi: int, thickness_mm: float, length_mm: float, tone: int = FAINT_BAR_TONE) -> Scene:
    """A horizontal bar of the given size on an empty sheet, well inside the margin."""
    return with_line(
        sheet(dpi), (30.0, 60.0), (30.0 + length_mm, 60.0), tone=tone, thickness_mm=thickness_mm
    )


# ---- the fixtures are marks to the plain detector, or the tests below would prove nothing ----


@pytest.mark.parametrize("tone", [152, 175, 190])
def test_the_crease_fixtures_are_marks_to_the_plain_detector(tone: int) -> None:
    page = colour_page(with_creases(sheet(300), tone=tone))
    assert len(find_marks(page, margin_mm=BLANK_MARGIN_MM)) == 2


def test_the_artefact_fixture_is_a_tall_mark_to_the_plain_detector() -> None:
    page = colour_page(with_slanted_artefact(sheet(200, TALL_MM)))
    (mark,) = find_marks(page, margin_mm=BLANK_MARGIN_MM)
    size = (mark.x1 - mark.x0, mark.y1 - mark.y0)
    assert size == pytest.approx((7.6 * 200 / 25.4, 153 * 200 / 25.4), abs=8)


# ---- pages that are blank: a creased back ----------------------------------------------------

LAYOUTS = {
    "horizontal": {},
    "horizontal, broken": {"broken": True},
    "vertical": {"vertical": True},
    "vertical, broken": {"vertical": True, "broken": True},
}


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize("layout", list(LAYOUTS))
def test_a_creased_blank_back_is_blank_at_every_resolution(dpi: int, layout: str) -> None:
    scene = with_creases(sheet(dpi), **LAYOUTS[layout])
    assert verdicts(scene) == BLANK


@pytest.mark.parametrize("tone", [152, 175, 190])
def test_creases_of_any_darkness_the_real_pages_had_are_blank(tone: int) -> None:
    assert verdicts(with_creases(sheet(300), tone=tone, broken=True)) == BLANK


@pytest.mark.parametrize("thickness_mm", [0.2, 0.35, 0.5])
def test_creases_of_any_thickness_the_real_pages_had_are_blank(thickness_mm: float) -> None:
    scene = with_creases(sheet(300), thickness_mm=thickness_mm, broken=True)
    assert verdicts(scene) == BLANK


def test_creases_with_show_through_texture_are_blank() -> None:
    front = sheet(300, seed=2)
    for row in range(6):
        front = with_text(front, 15, 15 + row * 9, 20)
    back = with_show_through(sheet(300, seed=5, noise=6), front, peak=30)
    creased = with_creases(back, broken=True)
    assert creased.image.min() < 240 - 60  # the creases are there
    assert verdicts(creased) == BLANK


def test_creases_among_dust_are_blank() -> None:
    creased = with_creases(with_specks(sheet(300), 40, max_px=8), broken=True)
    assert verdicts(creased) == BLANK


def test_a_faint_tall_artefact_is_blank() -> None:
    for dpi in (200, 300):
        assert verdicts(with_slanted_artefact(sheet(dpi, TALL_MM))) == BLANK


def test_creases_artefact_dust_and_texture_together_are_blank() -> None:
    """What one real back looked like: broken creases, the artefact, dust, paper texture."""
    scene = with_slanted_artefact(sheet(300, TALL_MM, noise=6))
    scene = with_creases(with_specks(scene, 40, max_px=8), broken=True, from_mm=20.0)
    assert verdicts(scene) == BLANK


# ---- pages that are not blank ----------------------------------------------------------------


@pytest.mark.parametrize("dpi", DPIS)
def test_a_line_of_dark_text_among_creases_keeps_the_page(dpi: int) -> None:
    scene = with_text(with_creases(sheet(dpi), broken=True), 25, 20, 6)
    assert verdicts(scene) == KEPT


@pytest.mark.parametrize("dpi", DPIS)
def test_pencil_handwriting_keeps_the_page(dpi: int) -> None:
    """Strokes darkest 110-150, letters 2.6 mm, a few words."""
    scene = with_pencil_words(sheet(dpi), 25, 20)
    assert verdicts(scene) == KEPT


@pytest.mark.parametrize("dpi", DPIS)
def test_pencil_handwriting_among_creases_keeps_the_page(dpi: int) -> None:
    scene = with_pencil_words(with_creases(sheet(dpi), broken=True), 25, 20)
    assert verdicts(scene) == KEPT


def test_pencil_at_the_faintest_level_still_keeps_the_page_by_its_round_letters() -> None:
    scene = with_pencil_words(sheet(300), 25, 20, "noon", tones=(FAINT_DARKEST + 10,))
    assert grey_verdicts(scene) == {"colour": False, "grey": False}


@pytest.mark.parametrize("tone", [40, 95])
def test_a_dark_ruled_line_alone_keeps_the_page(tone: int) -> None:
    scene = bar(300, 0.3, 60.0, tone=tone)
    assert verdicts(scene) == KEPT


def test_a_dark_ruled_line_among_creases_keeps_the_page() -> None:
    scene = with_creases(bar(300, 0.3, 60.0, tone=60), broken=True)
    assert verdicts(scene) == KEPT


@pytest.mark.parametrize("dpi", DPIS)
def test_a_small_dark_page_number_among_creases_keeps_the_page(dpi: int) -> None:
    scene = with_text(with_creases(sheet(dpi)), 50, 95, 1, tone=INK_TONE)
    assert verdicts(scene) == KEPT


# ---- the edges of the rule -------------------------------------------------------------------


def test_a_thin_line_just_darker_than_the_faint_level_counts() -> None:
    scene = bar(300, 0.3, 60.0, tone=FAINT_DARKEST - 1)
    assert grey_verdicts(scene) == {"colour": False, "grey": False}


def test_a_thin_line_at_the_faint_level_does_not() -> None:
    scene = bar(300, 0.3, 60.0, tone=FAINT_DARKEST)
    assert grey_verdicts(scene) == {"colour": True, "grey": True}


def test_a_faint_bar_that_is_neither_thin_nor_long_counts() -> None:
    """1 mm wide and 5 mm long: ratio 5, a faint mark of letter size is writing."""
    assert grey_verdicts(bar(300, 1.0, 5.0)) == {"colour": False, "grey": False}


def test_a_faint_bar_that_is_not_thin_but_many_times_longer_than_wide_does_not() -> None:
    """1.2 mm wide and 12 mm long: ratio 10, a line though thicker than a crease."""
    assert grey_verdicts(bar(300, 1.2, 12.0)) == {"colour": True, "grey": True}


def test_a_faint_thin_dash_that_is_not_many_times_longer_than_wide_does_not() -> None:
    """0.5 mm wide and 3 mm long: ratio 6, still thinner than a crease."""
    assert grey_verdicts(bar(300, 0.5, 3.0)) == {"colour": True, "grey": True}


def test_a_big_faint_block_still_keeps_the_page() -> None:
    scene = with_solid_block(sheet(300), 30, 30, 20, tone=FAINT_BAR_TONE)
    assert grey_verdicts(scene) == {"colour": False, "grey": False}


def test_the_constants_sit_between_the_numbers_of_the_real_pages() -> None:
    assert 120 < FAINT_DARKEST <= 152  # text is 120 or darker, creases are 152 or lighter
    assert 0.51 < LINE_MAX_MM < 1.0  # the thickest crease; a letter's stroke is wider than a mm
    assert 5 <= LINE_ASPECT < 20  # a pencil "l" is about 7; the artefact is about 20


# ---- the known limits, kept on the side of keeping the page --------------------------------


def test_dust_sitting_on_a_crease_keeps_the_page() -> None:
    """A dark speck makes the crease it touches one mark whose darkest pixel is not faint."""
    scene = with_solid_block(with_creases(sheet(300)), 50, 39.5, 0.9, tone=SPECK_TONE)
    assert grey_verdicts(scene) == {"colour": False, "grey": False}


def test_creases_that_cross_are_one_big_mark_and_keep_the_page() -> None:
    scene = with_creases(with_creases(sheet(300)), vertical=True)
    assert grey_verdicts(scene) == {"colour": False, "grey": False}


def test_a_lone_faint_pencil_stroke_may_be_ignored() -> None:
    """Known limit: a single faint stroke ("1", "l") is a thin faint line, like a crease."""
    scene = with_line(sheet(300), (50.0, 50.0), (50.0, 52.6), tone=150, thickness_mm=0.35)
    assert grey_verdicts(scene) == {"colour": True, "grey": True}


# ---- find_marks ------------------------------------------------------------------------------


def test_find_marks_keeps_returning_faint_lines_unless_told_to_ignore_them() -> None:
    """Trimming reads the same marks as before: only the blank rule asks for the new filter."""
    page = colour_page(with_creases(sheet(300)))
    assert len(find_marks(page)) == 2
    assert find_marks(page, ignore_faint_lines=True) == ()


def test_ignoring_faint_lines_leaves_the_other_marks_and_the_page_unchanged() -> None:
    page = colour_page(with_text(with_creases(sheet(300)), 25, 20, 4))
    before = page.pixels.copy()
    everything = find_marks(page)
    marks = find_marks(page, ignore_faint_lines=True)
    assert len(everything) == 6
    assert len(marks) == 4
    assert set(marks) <= set(everything)
    assert np.array_equal(page.pixels, before)
