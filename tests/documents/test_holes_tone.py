"""A hole is grey and neutral, and the two sides show the same grey: the darkest pixels of the
two sides are within ``HOLE_TONE_MATCH`` and the mean blue less red is within ``HOLE_TINT``.
Ink of a colour, or a dark mark against its pale ghost, is not the backing seen through paper."""

import pytest

from fastfoto_linux.documents.blank import is_blank_beside
from fastfoto_linux.documents.holes import HOLE_DARKEST_MIN, HOLE_TINT, HOLE_TONE_MATCH
from fastfoto_linux.documents.trim import trim_page
from tests.doc_synth import Scene
from tests.doc_synth_holes import STAPLES, Tone, holes_painter, sheet
from tests.documents.helpers import bw_page, grey_page
from tests.documents.holes_helpers import DPIS, blanks, mirrored

KEPT = (False, False)
BLANK = (True, True)
GREY = 100


def staples(dpi: int, front: Tone, back: Tone) -> tuple[Scene, Scene]:
    """The staple holes of a sheet, in ``front`` on one side and in ``back`` on the other."""
    return sheet(dpi, [holes_painter(STAPLES, front)], [holes_painter(mirrored(STAPLES), back)])


@pytest.mark.parametrize("dpi", DPIS)
def test_two_greys_that_differ_by_a_little_are_one_hole(dpi: int) -> None:
    """Real holes: darkest 89 to 100 on one side and 97 to 106 on the other."""
    assert blanks(*staples(dpi, 90, 90 + HOLE_TONE_MATCH - 12)) == BLANK


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize("gap", [HOLE_TONE_MATCH + 15, -HOLE_TONE_MATCH - 15], ids=str)
def test_two_greys_that_differ_by_a_lot_are_not(dpi: int, gap: int) -> None:
    """Marks of the same shape, one dark and one pale: ink and its ghost, not a hole."""
    assert blanks(*staples(dpi, 90, 90 + gap)) == KEPT


@pytest.mark.parametrize("dpi", DPIS)
def test_a_dark_mark_and_its_pale_ghost_are_not_a_hole(dpi: int) -> None:
    assert blanks(*staples(dpi, 70, 155)) == KEPT


@pytest.mark.parametrize("dpi", DPIS)
def test_a_grey_mark_opposite_a_black_one_is_not_a_hole_though_the_greys_are_near(
    dpi: int,
) -> None:
    """Within the match, but one side is as dark as ink: the back's mark is judged by what is
    opposite as well as by itself."""
    assert blanks(*staples(dpi, HOLE_DARKEST_MIN - 15, HOLE_DARKEST_MIN + 10)) == KEPT


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize("tint", [HOLE_TINT - 6, -HOLE_TINT + 6], ids=str)
def test_a_hole_that_is_a_little_off_neutral_is_still_a_hole(dpi: int, tint: int) -> None:
    """A real hole is neutral to within 4 levels of blue less red."""
    colour = (GREY + max(-tint, 0), GREY, GREY + max(tint, 0))
    assert blanks(*staples(dpi, colour, colour)) == BLANK


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize("ink", ["blue", "red"])
def test_ink_of_a_colour_is_not_a_hole(dpi: int, ink: str) -> None:
    """Blue or red ink as dark as a hole, at the mirrored spots of both sides."""
    strong = HOLE_TINT + 25
    colour = (GREY, GREY, GREY + strong) if ink == "blue" else (GREY + strong, GREY, GREY)
    assert blanks(*staples(dpi, colour, colour)) == KEPT


@pytest.mark.parametrize("dpi", DPIS)
def test_a_coloured_mark_over_a_grey_one_is_not_a_hole_either(dpi: int) -> None:
    blue = (GREY, GREY, GREY + HOLE_TINT + 25)
    assert blanks(*staples(dpi, GREY, blue)) == KEPT
    assert blanks(*staples(dpi, blue, GREY)) == KEPT


@pytest.mark.parametrize("kind", ["grey", "bw"])
def test_a_grey_page_has_holes_and_a_one_bit_page_has_none(kind: str) -> None:
    """A hole is as black as print on a page of only black and white, so nothing there is one."""
    front, back = staples(200, GREY, GREY)
    make = grey_page if kind == "grey" else bw_page
    first, second = trim_page(make(front)), trim_page(make(back))
    assert is_blank_beside(first, second) is (kind == "grey")
    assert is_blank_beside(second, first) is (kind == "grey")
