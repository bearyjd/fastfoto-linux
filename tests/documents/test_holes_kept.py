"""What is not a hole keeps its page: a mark with no mirror, a big one, one far from every edge,
a page number, writing, or a hole with nothing on the other side to show it."""

from dataclasses import replace

import pytest

from fastfoto_linux.documents.blank import is_blank_beside
from fastfoto_linux.documents.holes import EDGE_ZONE_MM, HOLE_MAX_MM
from tests.doc_synth import with_text
from tests.doc_synth_holes import (
    STAPLES,
    dash,
    disc,
    holes_painter,
    sheet,
    slanted,
    with_number,
)
from tests.documents.holes_helpers import (
    DPIS,
    PAPER_HEIGHT_MM,
    PAPER_WIDTH_MM,
    blanks,
    mirrored,
    trimmed_sides,
)

KEPT = (False, False)


@pytest.mark.parametrize("dpi", DPIS)
def test_holes_on_one_side_only_keep_that_page(dpi: int) -> None:
    front, back = sheet(dpi, [holes_painter(STAPLES)], [])
    assert blanks(front, back) == (False, True)  # the empty back is blank as ever


@pytest.mark.parametrize("dpi", DPIS)
def test_a_two_millimetre_mark_near_an_edge_with_no_mirror_keeps_the_back(dpi: int) -> None:
    extra = dash(60.0, 7.0, 2.0)  # near the top; nothing opposite on the front
    front, back = sheet(dpi, [holes_painter(STAPLES)], [holes_painter([*mirrored(STAPLES), extra])])
    assert blanks(front, back)[1] is False


@pytest.mark.parametrize("dpi", DPIS)
def test_a_mark_of_the_same_size_but_another_shape_opposite_is_not_a_hole(dpi: int) -> None:
    """The mirrored spot holds a dash lying across the mark: the same size, hardly any overlap."""
    flat, upright = dash(12.0, 6.0, 2.0, 0.7), dash(12.65, 5.35, 0.7, 2.0)
    front, back = sheet(dpi, [holes_painter([flat])], [holes_painter(mirrored([upright]))])
    assert blanks(front, back) == KEPT


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize("slope", [1, -1], ids=["slash", "backslash"])
def test_a_slanted_hole_that_is_not_flipped_on_the_other_side_is_not_a_hole(
    dpi: int, slope: int
) -> None:
    """Flipped, "/" is "\\": the same stroke at the mirrored spot lies across the mark."""
    hole = [slanted(12.0, 6.0, 2.4, slope)]
    unflipped = [replace(other, slope=-other.slope) for other in mirrored(hole)]
    front, back = sheet(dpi, [holes_painter(hole)], [holes_painter(unflipped)])
    assert blanks(front, back) == KEPT


@pytest.mark.parametrize("dpi", DPIS)
def test_the_same_marks_at_the_same_spot_of_both_sides_not_mirrored_keep_both_pages(
    dpi: int,
) -> None:
    front, back = sheet(dpi, [holes_painter(STAPLES)], [holes_painter(STAPLES)])
    assert blanks(front, back) == KEPT


@pytest.mark.parametrize("dpi", DPIS)
def test_marks_flipped_top_to_bottom_are_not_the_other_side_of_the_holes(dpi: int) -> None:
    """The top stays on top: the back of a sheet is its front flipped left to right only."""
    upside_down = [hole.flipped_down(PAPER_HEIGHT_MM) for hole in mirrored(STAPLES)]
    front, back = sheet(dpi, [holes_painter(STAPLES)], [holes_painter(upside_down)])
    assert blanks(front, back) == KEPT


@pytest.mark.parametrize("dpi", DPIS)
def test_a_ten_millimetre_mark_at_the_mirrored_spots_keeps_both_pages(dpi: int) -> None:
    big = [disc(10.0, 40.0, 10.0)]
    front, back = sheet(dpi, [holes_painter(big)], [holes_painter(mirrored(big))])
    assert blanks(front, back) == KEPT


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize(
    ("diameter", "blank"), [(HOLE_MAX_MM - 1, True), (HOLE_MAX_MM + 1, False)], ids=str
)
def test_a_mark_is_a_hole_up_to_eight_millimetres_and_not_over(
    dpi: int, diameter: float, blank: bool
) -> None:
    mark = [disc(10.0, 40.0, diameter)]
    front, back = sheet(dpi, [holes_painter(mark)], [holes_painter(mirrored(mark))])
    assert blanks(front, back) == (blank, blank)


@pytest.mark.parametrize("dpi", DPIS)
def test_a_hole_thirty_millimetres_from_every_edge_keeps_both_pages(dpi: int) -> None:
    mark = [disc(30.0, 30.0, 3.0)]
    assert min(30.0, 30.0, PAPER_WIDTH_MM - 33.0, PAPER_HEIGHT_MM - 33.0) > EDGE_ZONE_MM
    front, back = sheet(dpi, [holes_painter(mark)], [holes_painter(mirrored(mark))])
    assert blanks(front, back) == KEPT


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize(
    ("gap", "blank"), [(EDGE_ZONE_MM - 2.0, True), (EDGE_ZONE_MM + 2.0, False)], ids=str
)
def test_a_mark_is_a_hole_within_twenty_five_millimetres_of_an_edge_and_not_further(
    dpi: int, gap: float, blank: bool
) -> None:
    mark = [disc(gap, 40.0, 3.0)]
    front, back = sheet(dpi, [holes_painter(mark)], [holes_painter(mirrored(mark))])
    assert blanks(front, back) == (blank, blank)


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize(("reach", "blank"), [(1.8, True), (2.6, False)], ids=str)
@pytest.mark.parametrize("axis", [0, 1], ids=["sideways", "up and down"])
def test_the_other_side_may_lie_two_millimetres_off_and_not_further(
    dpi: int, reach: float, blank: bool, axis: int
) -> None:
    shift = (reach, 0.0) if axis == 0 else (0.0, reach)
    front, back = sheet(
        dpi, [holes_painter(STAPLES)], [holes_painter(mirrored(STAPLES))], shift_mm=shift
    )
    assert blanks(front, back) == (blank, blank)


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize(("other", "blank"), [(2.8, True), (3.2, False)], ids=str)
def test_the_shape_opposite_is_the_same_size_within_one_and_a_half_times(
    dpi: int, other: float, blank: bool
) -> None:
    """A 2 mm dash and a longer one that overlap by more than half (2.0 / 3.2 is 0.625), so only
    the size tells them apart."""
    short = [dash(12.0, 6.0, 2.0)]
    longer = [dash(12.0 - (other - 2.0) / 2, 6.0, other)]
    front, back = sheet(dpi, [holes_painter(short)], [holes_painter(mirrored(longer))])
    assert blanks(front, back) == (blank, blank)


@pytest.mark.parametrize("dpi", DPIS)
def test_a_pale_mark_at_the_mirrored_spot_is_not_a_hole(dpi: int) -> None:
    """A hole shows the dark backing; a mark only 55 levels darker than the paper is ink."""
    front, back = sheet(dpi, [holes_painter(STAPLES, 185)], [holes_painter(mirrored(STAPLES), 185)])
    first, second = trimmed_sides(front, back)
    assert not is_blank_beside(first, second)
    assert not is_blank_beside(second, first)


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize("numbers", [("1", "2"), ("3", "4"), ("10", "11")], ids="/".join)
def test_page_numbers_at_the_mirrored_bottom_centre_spot_keep_both_pages(
    dpi: int, numbers: tuple[str, str]
) -> None:
    def printed(digits: str):
        return lambda scene: with_number(scene, digits, centre_x_mm=50.0, y_mm=105.0)

    front, back = sheet(dpi, [printed(numbers[0])], [printed(numbers[1])])
    assert blanks(front, back) == KEPT


@pytest.mark.parametrize("dpi", DPIS)
def test_a_sheet_printed_on_both_sides_keeps_both_pages(dpi: int) -> None:
    def text(scene):
        return with_text(scene, 12.0, 40.0, 14)

    front, back = sheet(
        dpi, [text, holes_painter(STAPLES)], [text, holes_painter(mirrored(STAPLES))]
    )
    assert blanks(front, back) == KEPT


@pytest.mark.parametrize("dpi", DPIS)
def test_a_page_without_a_partner_is_judged_as_it_always_was(dpi: int) -> None:
    front, back = sheet(dpi, [holes_painter(STAPLES)], [holes_painter(mirrored(STAPLES))])
    first, second = trimmed_sides(front, back)
    assert is_blank_beside(first, None) is False
    assert is_blank_beside(second, None) is False
    empty = sheet(dpi)[0]
    assert is_blank_beside(trimmed_sides(empty, empty)[0], None) is True
