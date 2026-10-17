"""A dark speck on a crease is dust and a dark letter touching one is writing, as if alone.

The crease joins a speck into one mark; the page is kept only when a dark part of that mark
would be a mark by itself: at least a millimetre long and a third of a square millimetre.
Soft scans (blurred, tinted, shadowed along the folds) are judged the same way.
"""

import pytest

from tests.doc_synth import INK_TONE, SPECK_TONE, Scene, with_solid_block, with_text
from tests.doc_synth_creases import with_creases, with_line
from tests.doc_synth_faint import (
    SHADOW_LEVELS,
    softened,
    with_dust_on_creases,
)
from tests.documents.blank_helpers import (
    BLANK,
    DPIS,
    KEPT,
    KEPT_ALSO_IN_1_BIT,
    marks_of,
    sheet,
    verdicts,
)

PAPER_MM = (60.0, 50.0)  # small, so that 600 dpi stays fast; the crease at 40 mm is inside
DUSTY_MM = (100.0, 120.0)
CREASE_Y_MM = 40.0
CREASE_THICKNESS_MM = 0.3
CREASE_TONE = 175
SPECK_MM = 0.9  # under a millimetre
SEGMENTS_MM = [2.5, 4.0, 10.0]
# The top of the speck, so that it sits across the crease, on its upper side, or on its lower side.
SPECK_TOPS_MM = {"across": 39.7, "above": 39.4, "below": 40.0}
SOFT_CREASE_TONE = 180  # still 150 or lighter once the blur, the shadow and the tint are added
SOFT_DUST_MM = 0.6  # a blurred speck is a little bigger than it was


def creased(dpi: int, length_mm: float) -> Scene:
    """A crease segment of ``length_mm`` from x = 20 mm on an empty small sheet."""
    return with_line(
        sheet(dpi, PAPER_MM),
        (20.0, CREASE_Y_MM),
        (20.0 + length_mm, CREASE_Y_MM),
        tone=CREASE_TONE,
        thickness_mm=CREASE_THICKNESS_MM,
    )


def with_speck(scene: Scene, length_mm: float, top_mm: float, size_mm: float) -> Scene:
    """A dark square speck over the middle of a crease of ``length_mm``."""
    return with_solid_block(scene, 20.0 + (length_mm - size_mm) / 2, top_mm, size_mm, SPECK_TONE)


# ---- the fixtures: crease and speck are one mark to the plain detector -----------------------


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize("top", list(SPECK_TOPS_MM))
def test_a_speck_on_a_crease_makes_one_mark_with_it(dpi: int, top: str) -> None:
    scene = with_speck(creased(dpi, 4.0), 4.0, SPECK_TOPS_MM[top], SPECK_MM)
    (mark,) = marks_of(scene)
    assert (mark.x1 - mark.x0) * 25.4 / dpi == pytest.approx(4.0, abs=0.6)


# ---- dust on a crease is ignored -------------------------------------------------------------


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize("length_mm", SEGMENTS_MM)
@pytest.mark.parametrize("top", list(SPECK_TOPS_MM))
def test_a_speck_under_a_millimetre_on_a_crease_leaves_the_page_blank(
    dpi: int, length_mm: float, top: str
) -> None:
    scene = with_speck(creased(dpi, length_mm), length_mm, SPECK_TOPS_MM[top], SPECK_MM)
    assert verdicts(scene) == BLANK


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize("broken", [False, True])
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_dust_on_creases_leaves_the_page_blank(dpi: int, broken: bool, seed: int) -> None:
    scene = with_dust_on_creases(
        with_creases(sheet(dpi, DUSTY_MM), broken=broken), 24, max_mm=SPECK_MM, seed=seed
    )
    assert scene.image.min() == SPECK_TONE  # the dust is there
    assert marks_of(scene)
    assert verdicts(scene) == BLANK


# ---- known limit: a crease segment too short to show its course -----------------------------

SHORTEST_REAL_SEGMENT_MM = 2.0  # real creases come in segments of 2 to 23 mm
STUB_MM = 1.0


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize("top", list(SPECK_TOPS_MM))
def test_a_speck_at_the_end_of_the_shortest_real_segment_leaves_the_page_blank(
    dpi: int, top: str
) -> None:
    x_mm = 20.0 + SHORTEST_REAL_SEGMENT_MM - SPECK_MM / 2
    speck = with_solid_block(
        creased(dpi, SHORTEST_REAL_SEGMENT_MM), x_mm, SPECK_TOPS_MM[top], SPECK_MM, SPECK_TONE
    )
    assert verdicts(speck) == BLANK


@pytest.mark.parametrize("dpi", DPIS)
def test_a_speck_next_to_a_crease_segment_under_2_mm_long_keeps_the_page(dpi: int) -> None:
    """Known limit: a stub of a millimetre shows nothing of the crease's course, so the speck
    cannot be told from ink touching it."""
    assert marks_of(with_speck(creased(dpi, STUB_MM), STUB_MM, SPECK_TOPS_MM["across"], SPECK_MM))
    scene = with_speck(creased(dpi, STUB_MM), STUB_MM, SPECK_TOPS_MM["across"], SPECK_MM)
    assert verdicts(scene) == KEPT


THICK_CREASE_MM = 0.5  # the thickest real crease; a segment this thick and 2 mm long is squat
STUB_LIMIT_MM = 1.8  # under 2 mm; the speck sits in the middle, the segment shows no course


@pytest.mark.parametrize("dpi", DPIS)
def test_a_speck_at_the_end_of_the_squattest_real_segment_leaves_the_page_blank(dpi: int) -> None:
    """2 mm long and 0.5 thick: once the speck and its halo are taken off, what is left is no
    longer than 2.5 times its width, but the crease as a whole is."""
    crease = with_line(
        sheet(dpi, PAPER_MM),
        (20.0, CREASE_Y_MM),
        (20.0 + SHORTEST_REAL_SEGMENT_MM, CREASE_Y_MM),
        tone=CREASE_TONE,
        thickness_mm=THICK_CREASE_MM,
    )
    speck = with_solid_block(
        crease, 20.0 + SHORTEST_REAL_SEGMENT_MM - SPECK_MM / 2, CREASE_Y_MM - 0.3, SPECK_MM, 70
    )
    assert marks_of(speck)
    assert verdicts(speck) == BLANK


@pytest.mark.parametrize("dpi", [300, 600])
def test_a_speck_in_the_middle_of_a_crease_segment_of_1_8_mm_keeps_the_page(dpi: int) -> None:
    """Known limit, at 300 dpi and finer: what is left of the segment once the speck and its halo
    are taken off is a stub shorter than a mark, which shows nothing of the crease's course."""
    scene = with_speck(
        creased(dpi, STUB_LIMIT_MM), STUB_LIMIT_MM, SPECK_TOPS_MM["across"], SPECK_MM
    )
    assert verdicts(scene) == KEPT


# ---- writing on a crease is kept -------------------------------------------------------------


@pytest.mark.parametrize("dpi", DPIS)
def test_a_speck_of_a_millimetre_and_more_on_a_crease_keeps_the_page(dpi: int) -> None:
    scene = with_speck(creased(dpi, 10.0), 10.0, SPECK_TOPS_MM["across"] - 0.2, 1.3)
    assert verdicts(scene) == KEPT


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize("tone", [INK_TONE, 100, 120])
def test_a_dark_letter_touching_a_crease_keeps_the_page(dpi: int, tone: int) -> None:
    """The letter's stem stands on the crease, so they are one mark."""
    scene = with_text(creased(dpi, 20.0), 28.0, CREASE_Y_MM - 1.2, 1, tone=tone)
    assert len(marks_of(scene)) == 1
    assert verdicts(scene, one_bit=True) == KEPT_ALSO_IN_1_BIT


@pytest.mark.parametrize("dpi", DPIS)
def test_a_dark_letter_and_a_speck_on_one_crease_keep_the_page(dpi: int) -> None:
    scene = with_speck(creased(dpi, 20.0), 20.0, SPECK_TOPS_MM["across"], SPECK_MM)
    scene = with_text(scene, 32.0, CREASE_Y_MM - 1.2, 1, tone=INK_TONE)
    assert verdicts(scene) == KEPT


@pytest.mark.parametrize("dpi", DPIS)
def test_a_lone_speck_that_a_soft_scan_makes_a_mark_still_keeps_the_page(dpi: int) -> None:
    """Dust is taken off a faint line only: a speck on its own that the plain detector finds a
    mark (the blur grew it to a millimetre) is judged as it was."""
    speck = with_solid_block(sheet(dpi, PAPER_MM), 25.0, 20.0, SPECK_MM, SPECK_TONE)
    scene = softened(speck, blur_mm=0.15, shadow_levels=0)
    assert len(marks_of(scene)) == 1
    assert verdicts(scene) == KEPT


# ---- soft scans: blurred, tinted, shadowed ---------------------------------------------------


def soft_creases(dpi: int, *, broken: bool) -> Scene:
    return softened(with_creases(sheet(dpi, DUSTY_MM), tone=SOFT_CREASE_TONE, broken=broken))


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize("broken", [False, True])
def test_soft_creases_are_blank(dpi: int, broken: bool) -> None:
    scene = soft_creases(dpi, broken=broken)
    assert marks_of(scene)  # they are still marks to the plain detector
    assert scene.image.min() >= 150  # and as light as the real ones (152 and up)
    assert verdicts(scene) == BLANK


@pytest.mark.parametrize("dpi", DPIS)
def test_soft_creases_with_dust_on_them_are_blank(dpi: int) -> None:
    creases = with_creases(sheet(dpi, DUSTY_MM), tone=SOFT_CREASE_TONE, broken=True)
    scene = softened(with_dust_on_creases(creases, 24, max_mm=SOFT_DUST_MM))
    assert marks_of(scene)
    assert verdicts(scene) == BLANK


@pytest.mark.parametrize("dpi", DPIS)
def test_soft_creases_with_a_line_of_text_keep_the_page(dpi: int) -> None:
    scene = softened(
        with_text(with_creases(sheet(dpi, DUSTY_MM), tone=SOFT_CREASE_TONE), 25, 20, 6)
    )
    assert verdicts(scene) == KEPT


def test_the_shadow_along_the_folds_is_not_a_mark_itself() -> None:
    shadowed = softened(sheet(300, DUSTY_MM), blur_mm=0.0)
    assert SHADOW_LEVELS < 45
    assert marks_of(shadowed) == ()
