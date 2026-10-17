"""A mark that is a hole through the paper, shown at the mirrored spot of the other side, is not a
mark: staple holes and punched holes do not keep an otherwise blank page."""

from dataclasses import replace

import pytest

from fastfoto_linux.documents.blank import is_blank_beside
from tests.doc_synth import with_text
from tests.doc_synth_holes import PUNCHES, STAPLES, disc, holes_painter, sheet, slanted
from tests.documents.holes_helpers import ALIGNMENTS, DPIS, blanks, mirrored, trimmed_sides

STAPLE_DOTS = (disc(12.0, 6.0, 1.3), disc(15.0, 6.3, 1.5), disc(18.0, 5.9, 1.2))


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize("alignment", ALIGNMENTS)
def test_staple_holes_at_mirrored_spots_leave_both_sides_blank(dpi: int, alignment: str) -> None:
    shift, tilt = ALIGNMENTS[alignment]
    front, back = sheet(
        dpi,
        [holes_painter(STAPLES)],
        [holes_painter(mirrored(STAPLES))],
        shift_mm=shift,
        tilt_deg=tilt,
    )
    assert blanks(front, back) == (True, True)


@pytest.mark.parametrize("dpi", DPIS)
def test_the_staple_holes_are_marks_when_nothing_is_on_the_other_side(dpi: int) -> None:
    front, back = sheet(dpi, [holes_painter(STAPLES)], [holes_painter(mirrored(STAPLES))])
    first, second = trimmed_sides(front, back)
    assert not is_blank_beside(first, None)
    assert not is_blank_beside(second, None)


@pytest.mark.parametrize("dpi", DPIS)
def test_staple_holes_that_are_dots_leave_both_sides_blank(dpi: int) -> None:
    front, back = sheet(
        dpi,
        [holes_painter(STAPLE_DOTS)],
        [holes_painter(mirrored(STAPLE_DOTS))],
        shift_mm=(1.0, 0.5),
    )
    assert blanks(front, back) == (True, True)


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize("alignment", ALIGNMENTS)
def test_three_punched_holes_near_the_left_edge_and_the_right_edge_leave_both_sides_blank(
    dpi: int, alignment: str
) -> None:
    shift, tilt = ALIGNMENTS[alignment]
    front, back = sheet(
        dpi,
        [holes_painter(PUNCHES)],
        [holes_painter(mirrored(PUNCHES))],
        shift_mm=shift,
        tilt_deg=tilt,
    )
    assert blanks(front, back) == (True, True)


@pytest.mark.parametrize("dpi", DPIS)
def test_the_punched_holes_are_at_the_left_of_the_front_and_the_right_of_the_back(
    dpi: int,
) -> None:
    front, back = sheet(dpi, [holes_painter(PUNCHES)], [holes_painter(mirrored(PUNCHES))])
    first, second = trimmed_sides(front, back)
    width = first.page.pixels.shape[1]
    dark_front = (first.page.pixels.min(axis=2) < 160).nonzero()[1]
    dark_back = (second.page.pixels.min(axis=2) < 160).nonzero()[1]
    assert dark_front.max() < width / 4
    assert dark_back.min() > width * 3 / 4


@pytest.mark.parametrize("dpi", DPIS)
def test_the_side_with_text_keeps_its_page_and_the_empty_side_is_blank(dpi: int) -> None:
    def text(scene):
        return with_text(scene, 25.0, 50.0, 12)

    front, back = sheet(dpi, [holes_painter(STAPLES), text], [holes_painter(mirrored(STAPLES))])
    assert blanks(front, back) == (False, True)


@pytest.mark.parametrize("dpi", [200, 300])
@pytest.mark.parametrize("shift", [(0.0, 0.0), (-0.5, 0.8)], ids=str)
def test_holes_on_a_sheet_narrower_than_the_frame_are_matched_in_the_frame(
    dpi: int, shift: tuple[float, float]
) -> None:
    """The paper lies 3.5 mm from the front's left edge of a frame 8 mm wider than the sheet, so
    the back sees it 3.5 mm from ITS right edge: the trims cut a different strip from each side."""
    front, back = sheet(
        dpi,
        [holes_painter(STAPLES)],
        [holes_painter(mirrored(STAPLES))],
        frame_extra_mm=8.0,
        gap_mm=3.5,
        shift_mm=shift,
    )
    first, second = trimmed_sides(front, back)
    assert min(first.left, first.right, second.left, second.right) > 0
    assert first.left != second.left
    assert (is_blank_beside(first, second), is_blank_beside(second, first)) == (True, True)


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize("slope", [1, -1], ids=["slash", "backslash"])
def test_a_slanted_hole_is_the_other_way_round_on_the_other_side(dpi: int, slope: int) -> None:
    """The hole of a clip slanted like "/" on the front shows as "\\" on the back."""
    hole = [replace(slanted(12.0, 6.0, 1.2, slope), stroke_mm=0.5)]
    front, back = sheet(dpi, [holes_painter(hole)], [holes_painter(mirrored(hole))])
    assert blanks(front, back) == (True, True)
