"""A faint mark is ignored only when it is a straight thin line; writing never is.

Thin-pen cursive, a signature wave and a curved line are as faint and as thin as a crease but not
straight; dark ink that touches a crease (a hairline stem, a "7") would be a mark on its own, so it
is one on the crease. Known limits, kept on the side of ignoring a faint straight stroke: a lone
stem or a roman "ii" in faint thin pen is a pair of straight lines like any other.
"""

import itertools
from collections.abc import Callable

import pytest

from fastfoto_linux.documents.blank import is_blank
from tests.doc_synth import Scene, with_solid_block
from tests.doc_synth_creases import with_line, with_slanted_artefact
from tests.doc_synth_faint import (
    softened,
    with_bowed_line,
    with_cursive_word,
    with_roman_two,
    with_seven,
    with_stem,
    with_wave,
    with_zigzag,
)
from tests.documents.blank_helpers import (
    BLANK,
    DPIS,
    KEPT,
    TALL_MM,
    bar,
    marks_of,
    sheet,
    verdicts,
)
from tests.documents.helpers import colour_page

WORD_MM = (100.0, 60.0)
PENS_MM = [0.15, 0.2, 0.3]
FAINT_TONES = [150, 170]
CREASE_PAPER_MM = (60.0, 50.0)
CREASE_Y_MM = 40.0
CREASE_FROM_TO_MM = (20.0, 35.0)  # 15 mm long
BLURS_MM = [0.0, 0.15]
INK_TONES = [43, 120]
HAIRLINE_PENS_MM = [0.2, 0.25]
STEM_LENGTHS_MM = [1.0, 1.5]
MIN_CELLS = 8  # of 16 per shape and resolution, the stroke alone must be a mark in this many


def span_mm(scene: Scene) -> float:
    """How wide the marks of the scene spread, left to right."""
    marks = marks_of(scene)
    return (max(m.x1 for m in marks) - min(m.x0 for m in marks)) * 25.4 / scene.dpi


# ---- thin pen: a long word is not straight ---------------------------------------------------


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize("tone", FAINT_TONES)
@pytest.mark.parametrize("pen_mm", PENS_MM)
def test_a_faint_thin_pen_flat_cursive_word_keeps_the_page(
    dpi: int, tone: int, pen_mm: float
) -> None:
    """About 25 mm wide and 2.6 mm tall, in a pen 0.15 to 0.3 mm wide: far thinner than a crease
    on average, but a loop is never straight."""
    scene = with_cursive_word(sheet(dpi, WORD_MM), 30.0, 25.0, tone=tone, stroke_mm=pen_mm)
    assert span_mm(scene) > 23.0
    assert verdicts(scene) == KEPT


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize("pen_mm", [0.3, 0.5])
@pytest.mark.parametrize("amplitude_mm", [1.0, 2.5])
def test_a_faint_flat_signature_wave_keeps_the_page(
    dpi: int, pen_mm: float, amplitude_mm: float
) -> None:
    scene = with_wave(
        sheet(dpi, WORD_MM),
        10.0,
        30.0,
        tone=150,
        length_mm=75.0,
        amplitude_mm=amplitude_mm,
        stroke_mm=pen_mm,
    )
    assert span_mm(scene) > 70.0
    assert verdicts(scene) == KEPT


@pytest.mark.parametrize("dpi", DPIS)
def test_a_wave_that_is_straight_enough_is_a_line(dpi: int) -> None:
    """Known limit: a wave swinging 0.1 mm either side of a line is that line."""
    scene = with_wave(
        sheet(dpi, WORD_MM), 10.0, 30.0, tone=150, length_mm=75.0, amplitude_mm=0.1, stroke_mm=0.3
    )
    assert verdicts(scene) == BLANK


# ---- roman page numbers ----------------------------------------------------------------------


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize("tone", FAINT_TONES)
def test_a_faint_roman_ii_is_two_straight_strokes_and_may_be_ignored(dpi: int, tone: int) -> None:
    """Known limit: the stems of a faint "ii" are separate marks, each a faint straight stroke."""
    assert len(marks_of(with_roman_two(sheet(dpi), 50.0, 60.0, tone=tone))) == 2
    assert verdicts(with_roman_two(sheet(dpi), 50.0, 60.0, tone=tone)) == BLANK


@pytest.mark.parametrize("dpi", DPIS)
def test_a_faint_roman_ii_joined_in_cursive_keeps_the_page(dpi: int) -> None:
    scene = with_roman_two(sheet(dpi), 50.0, 60.0, tone=160, joined=True)
    assert verdicts(scene) == KEPT


@pytest.mark.parametrize("dpi", DPIS)
def test_a_faint_tight_zigzag_scribble_keeps_the_page(dpi: int) -> None:
    """Every tooth is a bit under a millimetre off the axis, too small to be a mark of its own, but
    the scribble as a whole is far from straight."""
    scene = with_zigzag(
        sheet(dpi, WORD_MM),
        20.0,
        30.0,
        40.0,
        tone=160,
        swing_mm=0.7,
        tooth_mm=1.2,
        stroke_mm=0.2,
    )
    assert len(marks_of(scene)) == 1
    assert verdicts(scene) == KEPT


# ---- curved and slanted ----------------------------------------------------------------------


@pytest.mark.parametrize("dpi", [200, 300])
@pytest.mark.parametrize("angle_run_mm", [15.0, 40.0, 90.0])
def test_a_slanted_faint_thin_line_is_a_line_whatever_its_slant(
    dpi: int, angle_run_mm: float
) -> None:
    """The line runs from (30, 40) down and ``angle_run_mm`` to the right over 90 mm."""
    scene = with_line(
        sheet(dpi, TALL_MM), (30.0, 40.0), (30.0 + angle_run_mm, 130.0), tone=170, thickness_mm=0.35
    )
    assert marks_of(scene)
    assert verdicts(scene) == BLANK


@pytest.mark.parametrize("dpi", DPIS)
def test_a_soft_tinted_slanted_artefact_is_blank(dpi: int) -> None:
    scene = softened(with_slanted_artefact(sheet(dpi, TALL_MM)), shadow_levels=0)
    assert marks_of(scene)
    assert verdicts(scene) == BLANK


@pytest.mark.parametrize("dpi", [200, 300])
@pytest.mark.parametrize("bow_mm", [0.0, 0.3])
def test_a_line_bowed_by_a_third_of_a_millimetre_over_153_mm_is_still_straight(
    dpi: int, bow_mm: float
) -> None:
    scene = with_bowed_line(sheet(dpi, TALL_MM), 30.0, 40.0, 153.0, bow_mm, tone=176, stroke_mm=0.4)
    assert verdicts(scene) == BLANK


@pytest.mark.parametrize("dpi", [200, 300])
def test_a_faint_line_bowed_by_3_mm_over_153_mm_is_not_straight(dpi: int) -> None:
    scene = with_bowed_line(sheet(dpi, TALL_MM), 30.0, 40.0, 153.0, 3.0, tone=176, stroke_mm=0.4)
    assert verdicts(scene) == KEPT


# ---- short faint blobs are not lines ---------------------------------------------------------


def test_a_faint_mark_not_much_longer_than_wide_counts() -> None:
    """A pencil comma, 1.2 mm long and 0.7 thick: thin, but squat."""
    assert verdicts(bar(300, 0.7, 1.2)) == KEPT


def test_a_faint_round_dot_counts() -> None:
    assert verdicts(with_solid_block(sheet(300), 40.0, 40.0, 1.2, 165)) == KEPT


# ---- dark ink touching a crease is ink -------------------------------------------------------


def crease(dpi: int) -> Scene:
    start, stop = CREASE_FROM_TO_MM
    return with_line(
        sheet(dpi, CREASE_PAPER_MM),
        (start, CREASE_Y_MM),
        (stop, CREASE_Y_MM),
        tone=175,
        thickness_mm=0.3,
    )


def stem_above(scene: Scene, length: float, tone: int, pen: float) -> Scene:
    return with_stem(scene, 27.0, CREASE_Y_MM - length, CREASE_Y_MM, tone=tone, stroke_mm=pen)


def stem_below(scene: Scene, length: float, tone: int, pen: float) -> Scene:
    return with_stem(scene, 27.0, CREASE_Y_MM, CREASE_Y_MM + length, tone=tone, stroke_mm=pen)


def seven_above(scene: Scene, length: float, tone: int, pen: float) -> Scene:
    """A "7" standing on the crease with the tip of its diagonal."""
    return with_seven(scene, 26.0, CREASE_Y_MM - 1.4 * length, length, tone=tone, stroke_mm=pen)


def seven_on(scene: Scene, length: float, tone: int, pen: float) -> Scene:
    """A "7" whose bar lies along the crease."""
    return with_seven(scene, 24.0, CREASE_Y_MM, length, tone=tone, stroke_mm=pen)


SHAPES: dict[str, Callable[[Scene, float, int, float], Scene]] = {
    "stem above": stem_above,
    "stem below": stem_below,
    "seven above": seven_above,
}


def cells() -> list[tuple[float, float, int, float]]:
    return list(itertools.product(BLURS_MM, STEM_LENGTHS_MM, INK_TONES, HAIRLINE_PENS_MM))


def soft(scene: Scene, blur_mm: float) -> Scene:
    return softened(scene, blur_mm=blur_mm, shadow_levels=0) if blur_mm else scene


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize("shape", list(SHAPES))
def test_a_stroke_that_is_a_mark_alone_is_one_on_a_crease(dpi: int, shape: str) -> None:
    """Wherever the stroke alone keeps a page, the same stroke touching a 15 mm crease does."""
    draw, lost, alone_kept = SHAPES[shape], [], 0
    for blur, length, tone, pen in cells():
        stroke = soft(draw(sheet(dpi, CREASE_PAPER_MM), length, tone, pen), blur)
        if is_blank(colour_page(stroke)):
            continue
        alone_kept += 1
        creased = soft(draw(crease(dpi), length, tone, pen), blur)
        if is_blank(colour_page(creased)):
            lost.append((blur, length, tone, pen))
    assert alone_kept >= MIN_CELLS
    assert len(lost) <= 1, lost


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize("tone", INK_TONES)
def test_a_hairline_stem_touching_a_crease_keeps_the_page(dpi: int, tone: int) -> None:
    scene = stem_above(crease(dpi), 1.5, tone, 0.25)
    assert verdicts(scene) == KEPT


@pytest.mark.parametrize("dpi", DPIS)
def test_a_seven_whose_bar_lies_along_a_crease_keeps_the_page(dpi: int) -> None:
    assert verdicts(seven_on(crease(dpi), 1.5, 43, 0.25)) == KEPT


@pytest.mark.parametrize("dpi", DPIS)
def test_a_hairline_stem_alone_keeps_the_page(dpi: int) -> None:
    assert verdicts(stem_above(sheet(dpi, CREASE_PAPER_MM), 1.5, 43, 0.25)) == KEPT
