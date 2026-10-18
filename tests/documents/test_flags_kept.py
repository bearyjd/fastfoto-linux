"""The flags of a page that stays: each has a page that sets it and a near miss that does not.

A flag only explains. Every page here is kept (or dropped) exactly as it was without the flags;
the tests say so too."""

import pytest

from fastfoto_linux.documents.draft import Flag
from tests.doc_synth_holes import STAPLES, holes_painter
from tests.documents import flags_helpers as fh
from tests.documents.flags_helpers import FAST_DPIS, assess_sides
from tests.documents.holes_helpers import mirrored

PRINT = fh.lines()


@pytest.mark.parametrize("dpi", FAST_DPIS)
def test_a_signature_alone_has_few_marks(dpi: int) -> None:
    _, back = assess_sides(dpi, PRINT, [fh.glyphs(40, 55, 2)])
    assert not back.verdict.blank
    assert Flag.FEW_MARKS in back.flags


@pytest.mark.parametrize("dpi", FAST_DPIS)
def test_four_marks_are_not_few(dpi: int) -> None:
    _, back = assess_sides(dpi, PRINT, [fh.glyphs(40, 55, 4)])
    assert not back.verdict.blank
    assert Flag.FEW_MARKS not in back.flags


@pytest.mark.parametrize("dpi", FAST_DPIS)
def test_one_big_mark_is_not_few(dpi: int) -> None:
    _, back = assess_sides(dpi, PRINT, [fh.block(30, 40, 30)])
    assert not back.verdict.blank
    assert len(back.marks) == 1
    assert Flag.FEW_MARKS not in back.flags


@pytest.mark.parametrize("dpi", FAST_DPIS)
def test_marks_near_the_edge_only_are_edge_only(dpi: int) -> None:
    _, back = assess_sides(dpi, PRINT, [fh.glyphs(8, 60, 3)])
    assert not back.verdict.blank
    assert Flag.EDGE_ONLY in back.flags


@pytest.mark.parametrize("dpi", FAST_DPIS)
def test_one_mark_inside_the_page_is_not_edge_only(dpi: int) -> None:
    _, back = assess_sides(dpi, PRINT, [fh.glyphs(8, 60, 3), fh.glyphs(45, 60, 1)])
    assert Flag.EDGE_ONLY not in back.flags
    _, centre = assess_sides(dpi, PRINT, [fh.glyphs(45, 60, 3)])
    assert Flag.EDGE_ONLY not in centre.flags


@pytest.mark.parametrize("dpi", FAST_DPIS)
def test_a_hole_with_nothing_opposite_is_hole_like(dpi: int) -> None:
    _, back = assess_sides(dpi, PRINT, [holes_painter(STAPLES)])
    assert not back.verdict.blank
    assert Flag.HOLE_LIKE in back.flags
    assert Flag.HOLES_MATCHED not in back.flags


@pytest.mark.parametrize("dpi", FAST_DPIS)
def test_black_print_near_the_edge_is_not_hole_like(dpi: int) -> None:
    _, back = assess_sides(dpi, PRINT, [fh.glyphs(8, 60, 3)])
    assert Flag.HOLE_LIKE not in back.flags


@pytest.mark.parametrize("dpi", FAST_DPIS)
def test_a_matched_hole_is_not_hole_like(dpi: int) -> None:
    front = [holes_painter(STAPLES), *PRINT]
    _, back = assess_sides(dpi, front, [holes_painter(mirrored(STAPLES)), fh.glyphs(40, 55, 4)])
    assert not back.verdict.blank
    assert Flag.HOLE_LIKE not in back.flags


@pytest.mark.parametrize("dpi", FAST_DPIS)
def test_pale_pencil_only_is_faint_only(dpi: int) -> None:
    _, back = assess_sides(dpi, PRINT, [fh.glyphs(30, 50, 8, fh.FAINT_TONE)])
    assert not back.verdict.blank
    assert Flag.FAINT_ONLY in back.flags


@pytest.mark.parametrize("dpi", FAST_DPIS)
def test_one_dark_mark_among_pale_ones_is_not_faint_only(dpi: int) -> None:
    painters = [fh.glyphs(30, 50, 8, fh.FAINT_TONE), fh.glyphs(30, 70, 1)]
    _, back = assess_sides(dpi, PRINT, painters)
    assert Flag.FAINT_ONLY not in back.flags


@pytest.mark.parametrize("dpi", FAST_DPIS)
def test_a_paler_copy_of_the_other_side_is_show_through(dpi: int) -> None:
    front, back = assess_sides(dpi, PRINT, [fh.ghost_of(PRINT, dpi)])
    assert not back.verdict.blank
    assert Flag.SHOW_THROUGH in back.flags
    assert Flag.SHOW_THROUGH not in front.flags  # the print is darker than its ghost, not paler


@pytest.mark.parametrize("dpi", FAST_DPIS)
def test_a_copy_that_is_not_mirrored_is_not_show_through(dpi: int) -> None:
    _, back = assess_sides(dpi, PRINT, [fh.ghost_of(PRINT, dpi, upside_down=True)])
    assert not back.verdict.blank
    assert Flag.SHOW_THROUGH not in back.flags


@pytest.mark.parametrize("dpi", FAST_DPIS)
def test_mirrored_print_of_the_same_tone_is_not_show_through(dpi: int) -> None:
    front, back = assess_sides(dpi, PRINT, [fh.ghost_of(PRINT, dpi, tone=30)])
    assert Flag.SHOW_THROUGH not in back.flags
    assert Flag.SHOW_THROUGH not in front.flags


@pytest.mark.parametrize("dpi", FAST_DPIS)
def test_a_back_with_no_partner_cannot_show_through(dpi: int) -> None:
    scene = fh.sheet(dpi, [], PRINT)[1]
    assessed = fh.assess_alone(scene)
    assert Flag.SHOW_THROUGH not in assessed.flags


def test_the_flags_of_a_page_that_stays_are_never_the_dropped_ones() -> None:
    _, back = assess_sides(200, PRINT, [fh.glyphs(40, 55, 2)])
    assert not back.flags & {Flag.CREASE_IGNORED, Flag.HOLES_MATCHED}
