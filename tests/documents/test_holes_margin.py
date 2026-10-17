"""A hole's shape is the whole dark shape, not the part inside the 5 mm blank margin.

The scanner's margin is not looked at, so a hole that straddles it is counted as a mark only where
it lies inside: its box is clipped, and the dark shape goes on beyond the box. The shape that is
matched with the other side is the whole one (the dark pixels joined to the counted mark), or a
hole that straddles the margin on one side and not on the other would never match, and a small
mark joined to a long dark line would be taken for a hole."""

import pytest

from fastfoto_linux.documents.blank import BLANK_MARGIN_MM, is_blank_beside
from fastfoto_linux.documents.holes import HOLE_MAX_MM, HOLE_TONE
from fastfoto_linux.documents.marks import find_marks
from fastfoto_linux.documents.trim import Trimmed
from tests.doc_synth_holes import Hole, dash, disc, holes_painter, sheet
from tests.documents.holes_helpers import DPIS, blanks, mirrored, trimmed_sides

# Staple holes whose dark shapes start 4.5 to 4.7 mm from the top: the margin cuts 0.3 to 0.5 mm
# off the top of each of them.
STRADDLERS = (dash(12.0, 4.6, 1.9, 1.2), dash(15.0, 4.5, 1.6, 1.3), disc(18.0, 4.7, 1.8))
# Punched holes 6 mm across, 2 mm from the left edge: the margin cuts 3 mm off each.
EDGE_PUNCHES = (disc(2.0, 20.0, 6.0), disc(2.0, 55.0, 6.0), disc(2.0, 90.0, 6.0))
# Straddling holes with the back off the front by up to 1.5 mm sideways and 0.3 mm up and down.
ALIGNMENTS = {
    "aligned": ((0.0, 0.0), 0.0),
    "offset": ((1.5, 0.3), 0.0),
    "offset and tilted": ((-0.8, -0.2), 0.3),
}
KEPT = (False, False)
LINE_TOP_MM = 3.4  # a dark line along the top edge: wholly inside the margin
STEM_MM = (0.9, 3.4)  # a stem hanging from the line: 1.6 mm of it lie below the margin


def marks_of(side: Trimmed):
    return find_marks(
        side.page,
        margin_mm=BLANK_MARGIN_MM,
        trimmed_bottom=side.tail_rows,
        ignore_faint_lines=True,
    )


def dark_above_the_box(side: Trimmed) -> list[bool]:
    """For every counted mark of ``side``, whether its dark shape goes on above the counted box."""
    pixels = side.page.pixels
    return [
        bool((pixels[: mark.y0, mark.x0 : mark.x1].min(axis=2) < HOLE_TONE).any())
        for mark in marks_of(side)
    ]


def hung_from_a_line(length_mm: float) -> list[Hole]:
    """A dark line along the top edge, inside the margin, with a stem hanging from it."""
    line = Hole(30.0, LINE_TOP_MM, length_mm, 0.8)
    stem = Hole(30.0 + length_mm / 2, LINE_TOP_MM, *STEM_MM)
    return [line, stem]


@pytest.mark.parametrize("dpi", DPIS)
def test_the_margin_cuts_a_straddling_hole_and_its_dark_shape_goes_on_beyond_the_box(
    dpi: int,
) -> None:
    front, back = sheet(dpi, [holes_painter(STRADDLERS)], [holes_painter(mirrored(STRADDLERS))])
    for side in trimmed_sides(front, back):
        assert len(marks_of(side)) == len(STRADDLERS)
        assert all(dark_above_the_box(side))


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize("alignment", ALIGNMENTS)
def test_staple_holes_that_straddle_the_margin_leave_both_sides_blank(
    dpi: int, alignment: str
) -> None:
    shift, tilt = ALIGNMENTS[alignment]
    front, back = sheet(
        dpi,
        [holes_painter(STRADDLERS)],
        [holes_painter(mirrored(STRADDLERS))],
        shift_mm=shift,
        tilt_deg=tilt,
    )
    assert blanks(front, back) == (True, True)


@pytest.mark.parametrize("dpi", DPIS)
def test_staple_holes_that_straddle_the_margin_on_the_back_only_leave_both_sides_blank(
    dpi: int,
) -> None:
    """The front's holes lie a little lower, wholly below the margin: the back's are cut."""
    lower = [hole.moved(dy_mm=0.9) for hole in STRADDLERS]
    front, back = sheet(dpi, [holes_painter(lower)], [holes_painter(mirrored(STRADDLERS))])
    assert blanks(front, back) == (True, True)


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize("alignment", ALIGNMENTS)
def test_punched_holes_that_straddle_the_left_and_right_margin_leave_both_sides_blank(
    dpi: int, alignment: str
) -> None:
    shift, tilt = ALIGNMENTS[alignment]
    front, back = sheet(
        dpi,
        [holes_painter(EDGE_PUNCHES)],
        [holes_painter(mirrored(EDGE_PUNCHES))],
        shift_mm=shift,
        tilt_deg=tilt,
    )
    assert blanks(front, back) == (True, True)


@pytest.mark.parametrize("dpi", DPIS)
def test_holes_wholly_inside_the_margin_are_not_marks_at_all(dpi: int) -> None:
    inside = [hole.moved(dy_mm=-3.5) for hole in STRADDLERS]
    front, back = sheet(dpi, [holes_painter(inside)], [holes_painter(mirrored(inside))])
    first, second = trimmed_sides(front, back)
    assert marks_of(first) == () == marks_of(second)
    assert is_blank_beside(first, None) and is_blank_beside(second, None)
    assert blanks(front, back) == (True, True)


@pytest.mark.parametrize("dpi", DPIS)
def test_a_straddling_hole_with_no_hole_opposite_keeps_the_page(dpi: int) -> None:
    front, back = sheet(dpi, [], [holes_painter(mirrored(STRADDLERS))])
    assert blanks(front, back) == (True, False)


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize(
    ("length", "blank"), [(HOLE_MAX_MM - 1.0, True), (HOLE_MAX_MM + 1.0, False)], ids=str
)
def test_the_whole_shape_is_a_hole_up_to_eight_millimetres_and_not_over(
    dpi: int, length: float, blank: bool
) -> None:
    """A stem hangs from a line in the margin: the shape is the line and the stem together."""
    shape = hung_from_a_line(length)
    front, back = sheet(dpi, [holes_painter(shape)], [holes_painter(mirrored(shape))])
    assert blanks(front, back) == (blank, blank)


@pytest.mark.parametrize("dpi", DPIS)
def test_a_small_mark_joined_to_a_long_dark_line_near_the_edge_is_kept(dpi: int) -> None:
    """The part of the stem below the margin is a 1.6 mm mark, the very shape of the dash on the
    back; but on the front it hangs from a 30 mm line, and that is content."""
    stem_below = mirrored([Hole(45.0, 5.0, *STEM_MM[:1], 1.8)])
    front, back = sheet(dpi, [holes_painter(hung_from_a_line(30.0))], [holes_painter(stem_below)])
    first, second = trimmed_sides(front, back)
    assert len(marks_of(first)) == len(marks_of(second)) == 1
    assert all(dark_above_the_box(first))
    assert not is_blank_beside(first, second)
