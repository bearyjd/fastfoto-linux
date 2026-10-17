"""One sheet, one registration: every hole of a page lies at the same offset from its mirror
(real holes: within 0.1 mm of each other), whatever that offset is. Marks that happen to look
like the other side's lie at arbitrary offsets inside the search window."""

import pytest

from fastfoto_linux.documents.holes import OFFSET_SPREAD_MM
from tests.doc_synth import Scene
from tests.doc_synth_holes import Hole, dash, disc, holes_painter, sheet
from tests.documents.holes_helpers import DPIS, PAPER_WIDTH_MM, blanks, mirrored

KEPT = (False, False)
BLANK = (True, True)
TOP, FOOT = dash(12.0, 8.0, 1.8, 0.7), dash(12.0, 60.0, 1.8, 0.7)  # 52 mm apart


def apart(by_x: float, by_y: float, dpi: int) -> tuple[Scene, Scene]:
    """Two holes whose mirrors lie 1.0 mm right and 0.5 mm down of where they should, the second
    one ``by_x`` and ``by_y`` further."""
    back = [mirrored([TOP])[0].moved(1.0, 0.5), mirrored([FOOT])[0].moved(1.0 + by_x, 0.5 + by_y)]
    return sheet(dpi, [holes_painter([TOP, FOOT])], [holes_painter(back)])


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize("axis", [(1, 0), (0, 1)], ids=["across", "down"])
def test_holes_at_nearly_the_same_offset_are_holes(dpi: int, axis: tuple[int, int]) -> None:
    gap = OFFSET_SPREAD_MM - 0.3
    assert blanks(*apart(axis[0] * gap, axis[1] * gap, dpi)) == BLANK


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize("axis", [(1, 0), (0, 1)], ids=["across", "down"])
@pytest.mark.parametrize("sign", [1, -1], ids=["after", "before"])
def test_holes_at_different_offsets_are_not_holes(
    dpi: int, axis: tuple[int, int], sign: int
) -> None:
    """Each mark has a mirror inside the window, but not at one registration: chance."""
    gap = sign * (OFFSET_SPREAD_MM + 0.7)
    assert blanks(*apart(axis[0] * gap, axis[1] * gap, dpi)) == KEPT


def like(hole: Hole, width_mm: float, height_mm: float) -> Hole:
    """The mirror of ``hole`` as another shape, of ``width_mm`` by ``height_mm``, on the same
    centre: the two sides of a real hole are not the same shape."""
    centre_x = PAPER_WIDTH_MM - hole.x_mm - hole.width_mm / 2
    centre_y = hole.y_mm + hole.height_mm / 2
    return Hole(centre_x - width_mm / 2, centre_y - height_mm / 2, width_mm, height_mm)


# Holes like the real ones: grey 90 to 106, 0.7 to 1.2 mm, two sides that overlap by about 0.6.
FRONT = [dash(12.0, 6.0, 1.2, 0.7), dash(14.4, 6.3, 1.0, 0.7), dash(16.5, 5.8, 1.1, 0.8)]
BACK = [like(FRONT[0], 0.9, 0.9), like(FRONT[1], 0.8, 0.9), like(FRONT[2], 0.9, 1.0)]
OFFSETS = [(1.3, -0.7), (0.7, 0.2), (0.0, 0.0)]


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize("shift", OFFSETS, ids=str)
def test_holes_like_the_real_ones_are_blank_at_every_resolution(
    dpi: int, shift: tuple[float, float]
) -> None:
    front, back = sheet(
        dpi, [holes_painter(FRONT, 102)], [holes_painter(BACK, 95)], shift_mm=shift, seed=2
    )
    assert blanks(front, back) == BLANK


# How far the back may be off the front, as measured: the search window is SHIFT_MM (2.0 mm), and
# a hole is found as far out as its overlap allows, so a bigger hole is found further out.
STAPLE, PUNCH = [dash(12.0, 8.0, 1.8, 0.7)], [disc(8.0, 20.0, 6.0)]
TOLERANCE = [
    (STAPLE, 2.0, True),
    (STAPLE, 2.5, True),
    (STAPLE, 3.0, False),
    (PUNCH, 3.0, True),
    (PUNCH, 3.5, True),
    (PUNCH, 4.0, False),
]


@pytest.mark.parametrize(("holes", "shift", "blank"), TOLERANCE, ids=lambda v: str(v)[:12])
def test_the_offset_a_hole_is_found_at_is_the_window_for_small_holes_and_more_for_big_ones(
    holes: list[Hole], shift: float, blank: bool
) -> None:
    front, back = sheet(
        200, [holes_painter(holes)], [holes_painter(mirrored(holes))], shift_mm=(shift, 0.0)
    )
    assert blanks(front, back)[1] is blank
