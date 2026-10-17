"""Where the neighbour rule stops: creases stay ignored, and so do a lone stroke and lone rules.

A faint line is writing when another mark lies beside it: at least ``INNER_MM`` and at most
``OUTER_MM`` off its axis, alongside it. Creases have nothing beside them (the pieces of one crease
lie end to end, dust is smaller than a mark), so they stay ignored; a stroke with nothing beside it
is still a line, and the rule never turns a mark that was kept into one that is ignored.
"""

import math
from collections.abc import Callable

import pytest

from fastfoto_linux.documents import marks
from fastfoto_linux.documents.blank import BLANK_MARGIN_MM
from fastfoto_linux.documents.marks import find_marks
from tests.doc_synth import Scene, with_specks
from tests.doc_synth_creases import (
    with_creases,
    with_line,
    with_pencil_words,
    with_slanted_artefact,
)
from tests.doc_synth_faint import softened, with_dust_on_creases, with_roman_two, with_stem
from tests.doc_synth_text import pale_text_page, paragraph, with_serif_text
from tests.documents.blank_helpers import BLANK, DPIS, KEPT, TALL_MM, marks_of, sheet, verdicts
from tests.documents.helpers import colour_page

BAR_TONE = 170
BAR_MM = 0.3
LEFT_MM, RIGHT_MM, ROW_MM = 30.0, 45.0, 60.0  # the first bar of a pair
ARTEFACT_RUN_MM = 153.0
SLANT = math.tan(math.radians(2.8))
FRAGMENT_MM = 0.7  # shorter than a mark (a millimetre): dust
LONE_STROKES = ["l", "I", "!", "i", "j"]
LONE_SETTING = (10, 170, 0.114)  # points, darkest, blur in mm


def bars(dpi: int, rows: list[tuple[float, float, float]]) -> Scene:
    """Horizontal bars as thin as a crease; each row is (left, right, y) in millimetres."""
    scene = sheet(dpi)
    for left, right, row in rows:
        scene = with_line(scene, (left, row), (right, row), tone=BAR_TONE, thickness_mm=BAR_MM)
    return scene


def pair(dpi: int, gap_mm: float) -> Scene:
    """Two bars 15 mm long, one above the other, ``gap_mm`` apart axis to axis."""
    return bars(dpi, [(LEFT_MM, RIGHT_MM, ROW_MM), (LEFT_MM, RIGHT_MM, ROW_MM + gap_mm)])


# ---- how near is beside ----------------------------------------------------------------------


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize("gap_mm", [1.0, 2.0, 3.6])
def test_a_bar_with_another_beside_it_is_writing(dpi: int, gap_mm: float) -> None:
    assert len(marks_of(pair(dpi, gap_mm))) == 2
    assert verdicts(pair(dpi, gap_mm)) == KEPT


@pytest.mark.parametrize("dpi", DPIS)
def test_a_second_stroke_hugging_the_first_is_the_same_line(dpi: int) -> None:
    """0.6 mm off the axis is on the line: a crease drawn twice, or a doubled edge."""
    assert verdicts(pair(dpi, 0.6)) == BLANK


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize("gap_mm", [4.8, 7.0, 12.0])
def test_bars_further_apart_than_the_outer_reach_are_each_alone(dpi: int, gap_mm: float) -> None:
    """Ruled paper is 6 to 8 mm between rules: the rules stay lines."""
    assert len(marks_of(pair(dpi, gap_mm))) == 2
    assert verdicts(pair(dpi, gap_mm)) == BLANK


@pytest.mark.parametrize("dpi", DPIS)
def test_a_neighbour_must_lie_alongside_not_beyond_the_end(dpi: int) -> None:
    """Two pieces of one crease, the second 1 mm on and 1.5 mm off: not beside, but end to end."""
    scene = bars(dpi, [(LEFT_MM, RIGHT_MM, ROW_MM), (RIGHT_MM + 1.0, 60.0, ROW_MM + 1.5)])
    assert len(marks_of(scene)) == 2
    assert verdicts(scene) == BLANK


@pytest.mark.parametrize("dpi", DPIS)
def test_ruled_lines_and_a_dashed_line_are_ignored(dpi: int) -> None:
    rules = bars(dpi, [(LEFT_MM, 70.0, 30.0 + 7.0 * number) for number in range(5)])
    dashes = bars(dpi, [(20.0 + 5.0 * n, 23.0 + 5.0 * n, ROW_MM) for n in range(8)])
    assert len(marks_of(rules)) == 5
    assert len(marks_of(dashes)) == 8
    assert verdicts(rules) == BLANK
    assert verdicts(dashes) == BLANK


def test_the_reach_lies_between_a_crease_and_ruled_paper() -> None:
    """Over the thickest crease measured (0.51 mm) and under the narrowest ruled paper (6.35 mm)."""
    assert 0.51 < marks.INNER_MM <= 1.0
    assert 3.0 <= marks.OUTER_MM < 6.35


@pytest.mark.parametrize("dpi", DPIS)
def test_the_foot_of_a_line_is_not_a_neighbour_of_it(dpi: int) -> None:
    """A 25 mm faint stroke with a 1.5 mm foot: the foot lies 0.8 to 1.6 mm off the axis, but it is
    part of the line, not another mark beside it."""
    scene = with_line(sheet(dpi), (50.0, 40.0), (50.0, 65.0), tone=BAR_TONE, thickness_mm=BAR_MM)
    scene = with_line(scene, (50.0, 65.0), (51.5, 65.0), tone=BAR_TONE, thickness_mm=BAR_MM)
    assert len(marks_of(scene)) == 1
    assert verdicts(scene) == BLANK


# ---- what is not a neighbour -----------------------------------------------------------------


def fragments(scene: Scene, length_mm: float) -> Scene:
    """Specks ``length_mm`` long and 0.17 mm thick, 2 to 4 mm to either side of the artefact."""
    for number, offset in enumerate([2.0, 2.8, 3.4, 3.8, -2.0, -2.8, -3.4, -3.8]):
        top = 60.0 + 17.0 * number
        left = 6.0 + (top - 50.0) * SLANT + offset
        scene = with_line(scene, (left, top), (left, top + length_mm), tone=176, thickness_mm=0.17)
    return scene


@pytest.mark.parametrize(("dpi", "length_mm"), [(200, 0.7), (300, 0.7), (600, 0.7), (200, 1.1)])
def test_thin_fragments_beside_the_slanted_artefact_are_not_neighbours(
    dpi: int, length_mm: float
) -> None:
    """The neighbours must be marks themselves: dust beside a line does not make it writing."""
    scene = fragments(with_slanted_artefact(sheet(dpi, TALL_MM)), length_mm)
    assert len(marks_of(scene)) == 1  # the artefact; the fragments are no marks
    assert verdicts(scene) == BLANK


@pytest.mark.parametrize("dpi", DPIS)
def test_a_speck_beside_a_bar_is_not_a_neighbour(dpi: int) -> None:
    scene = with_line(
        bars(dpi, [(LEFT_MM, 60.0, ROW_MM)]),
        (44.0, ROW_MM + 2.0),
        (44.0, ROW_MM + 2.0 + FRAGMENT_MM),
        tone=176,
        thickness_mm=0.17,
    )
    assert len(marks_of(scene)) == 1
    assert verdicts(scene) == BLANK


def slanted_pieces(dpi: int) -> Scene:
    """A crease 2.8 degrees off vertical in five pieces 20 mm long with 5 mm between them."""
    scene = sheet(dpi, TALL_MM)
    for number in range(5):
        start = 40.0 + 25.0 * number
        scene = with_line(
            scene,
            (30.0 + (start - 40.0) * SLANT, start),
            (30.0 + (start + 20.0 - 40.0) * SLANT, start + 20.0),
            tone=175,
            thickness_mm=0.3,
        )
    return scene


@pytest.mark.parametrize("dpi", DPIS)
def test_pieces_of_a_slanted_crease_lie_end_to_end_and_stay_ignored(dpi: int) -> None:
    assert len(marks_of(slanted_pieces(dpi))) == 5
    assert verdicts(slanted_pieces(dpi)) == BLANK


# ---- the creased back of a real letter -------------------------------------------------------


@pytest.mark.parametrize("dpi", DPIS)
def test_soft_tinted_creases_are_blank(dpi: int) -> None:
    scene = softened(with_creases(sheet(dpi), broken=True))
    assert marks_of(scene)
    assert verdicts(scene) == BLANK


def test_creases_the_artefact_dust_and_fragments_together_are_blank() -> None:
    """What one real back looked like, with specks 2 to 4 mm beside the artefact."""
    scene = fragments(with_slanted_artefact(sheet(300, TALL_MM, noise=6)), FRAGMENT_MM)
    scene = with_creases(scene, broken=True, from_mm=20.0)
    scene = with_dust_on_creases(with_specks(scene, 40, max_px=8), 30, max_mm=0.6)
    assert verdicts(scene) == BLANK


# ---- a stroke with nothing beside it is still a line -----------------------------------------


@pytest.mark.parametrize("dpi", DPIS)
def test_a_lone_faint_stem_may_be_ignored(dpi: int) -> None:
    """Known limit: one stroke, nothing beside it."""
    assert verdicts(with_stem(sheet(dpi), 50.0, 60.0, 62.6, tone=150, stroke_mm=0.3)) == BLANK


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize("stem_gap_mm", [5.0, 9.0])
def test_stems_further_apart_than_the_outer_reach_are_lone_strokes(
    dpi: int, stem_gap_mm: float
) -> None:
    scene = with_stem(sheet(dpi), 40.0, 60.0, 62.6, tone=150, stroke_mm=0.3)
    scene = with_stem(scene, 40.0 + stem_gap_mm, 60.0, 62.6, tone=150, stroke_mm=0.3)
    assert verdicts(scene) == BLANK


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize("glyph", LONE_STROKES)
def test_a_lone_faint_l_or_i_or_bang_may_be_ignored(dpi: int, glyph: str) -> None:
    points, darkest, blur_mm = LONE_SETTING
    page = pale_text_page(
        dpi,
        [(15.0, 10.0, glyph)],
        points=points,
        darkest=darkest,
        blur_mm=blur_mm,
        size_mm=(40.0, 30.0),
    )
    assert find_marks(page, margin_mm=BLANK_MARGIN_MM)
    assert not find_marks(page, margin_mm=BLANK_MARGIN_MM, ignore_faint_lines=True)


@pytest.mark.parametrize(
    ("text", "dpi", "points", "blur_mm"),
    [
        ("www.example.com | 555-0100 | info@example.com", 200, 8, 0.114),
        ("Page 1 of 3   Confidential   generated 2026-10-17", 300, 6, 0.09),
    ],
)
def test_text_so_pale_and_small_that_a_few_stems_register_may_be_ignored(
    text: str, dpi: int, points: int, blur_mm: float
) -> None:
    """Known limit: 6 to 8 pt at 190, where the plain detector finds 3 marks or fewer."""
    page = pale_text_page(
        dpi,
        [(8.0, 10.0, text)],
        points=points,
        darkest=190,
        blur_mm=blur_mm,
        size_mm=(110.0, 25.0),
    )
    assert 1 <= len(find_marks(page, margin_mm=BLANK_MARGIN_MM)) <= 3
    assert not find_marks(page, margin_mm=BLANK_MARGIN_MM, ignore_faint_lines=True)


# ---- the rule only ever turns an ignored line back into a mark -------------------------------


def corpus(dpi: int) -> dict[str, Callable[[], Scene]]:
    return {
        "creases": lambda: with_creases(sheet(dpi), broken=True),
        "artefact": lambda: fragments(with_slanted_artefact(sheet(dpi, TALL_MM)), FRAGMENT_MM),
        "slanted pieces": lambda: slanted_pieces(dpi),
        "pencil": lambda: with_pencil_words(sheet(dpi), 20.0, 40.0),
        "serif": lambda: with_serif_text(sheet(dpi), 10.0, 10.0, 12, tone=165, rows=2),
        "pair": lambda: pair(dpi, 2.0),
        "far pair": lambda: pair(dpi, 9.0),
        "ruled": lambda: bars(dpi, [(LEFT_MM, 70.0, 30.0 + 7.0 * n) for n in range(4)]),
        "lone stem": lambda: with_stem(sheet(dpi), 50.0, 60.0, 62.6, tone=150, stroke_mm=0.3),
        "roman ii": lambda: with_roman_two(sheet(dpi), 50.0, 60.0, tone=160),
    }


@pytest.mark.parametrize("dpi", [200, 300])
def test_the_rule_only_turns_ignored_lines_back_into_marks(
    dpi: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With the reach closed (outer = inner) there is no side zone: the rule of the straight-line
    round. It keeps no page the rule round it would drop, and it keeps some the earlier one lost."""
    gained = 0
    for name, make in corpus(dpi).items():
        page = colour_page(make())
        every = set(find_marks(page, margin_mm=BLANK_MARGIN_MM))
        with monkeypatch.context() as patch:
            patch.setattr(marks, "OUTER_MM", marks.INNER_MM)
            before = set(find_marks(page, margin_mm=BLANK_MARGIN_MM, ignore_faint_lines=True))
        after = set(find_marks(page, margin_mm=BLANK_MARGIN_MM, ignore_faint_lines=True))
        assert before <= after <= every, name
        gained += len(after - before)
    assert gained > 0


def test_a_page_of_pale_type_gains_every_stem_the_straight_line_rule_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = pale_text_page(200, paragraph(10), points=10, darkest=190, blur_mm=0.114)
    with monkeypatch.context() as patch:
        patch.setattr(marks, "OUTER_MM", marks.INNER_MM)
        before = find_marks(page, margin_mm=BLANK_MARGIN_MM, ignore_faint_lines=True)
    after = find_marks(page, margin_mm=BLANK_MARGIN_MM, ignore_faint_lines=True)
    assert before == ()
    assert len(after) > 40
