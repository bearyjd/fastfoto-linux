"""A hole is small or a round disc: only a staple hole (a whole shape of at most ``STAPLE_MAX_MM``)
or a punched hole (a filled disc of ``PUNCH_MIN_MM`` to ``HOLE_MAX_MM``) can be one. Real staple
holes are 0.6 to 1.35 mm long, grey 86 to 108; a printed digit is 2 to 3 mm tall and not round.
Anything in between, and a long thin or hollow mark, keeps its page, whatever lies opposite."""

from collections.abc import Callable

import pytest

from fastfoto_linux.documents.holes import HOLE_MAX_MM, PUNCH_MIN_MM, STAPLE_MAX_MM
from tests.doc_synth import Scene
from tests.doc_synth_holes import Hole, dash, disc, holes_painter, ring, sheet
from tests.documents.holes_helpers import FAST_DPIS, blanks, mirrored

KEPT = (False, False)
BLANK = (True, True)
# Staple holes as measured on real pages: (long side, short side, darkest) in mm and levels.
REAL_STAPLES = [(0.6, 0.42, 86), (0.9, 0.6, 96), (1.2, 0.7, 100), (1.35, 0.93, 108)]


def pair(
    dpi: int, marks: list[Hole], *, tone: int = 110, other: list[Hole] | None = None
) -> tuple[Scene, Scene]:
    """A sheet with ``marks`` on the front and, mirrored, ``other`` (or the same) on the back."""
    return sheet(dpi, [holes_painter(marks, tone)], [holes_painter(mirrored(other or marks), tone)])


@pytest.mark.parametrize("dpi", FAST_DPIS)
@pytest.mark.parametrize(("long", "short", "tone"), REAL_STAPLES, ids=str)
def test_staple_holes_as_small_and_as_grey_as_the_real_ones_are_holes(
    dpi: int, long: float, short: float, tone: int
) -> None:
    holes = [dash(12.0, 6.0, long, short), dash(16.0, 6.2, long, short)]
    assert blanks(*pair(dpi, holes, tone=tone)) == BLANK


@pytest.mark.parametrize("dpi", FAST_DPIS)
@pytest.mark.parametrize("diameter", [PUNCH_MIN_MM + 0.5, 6.0, 7.5], ids=str)
def test_a_round_disc_of_a_punched_hole_is_a_hole(dpi: int, diameter: float) -> None:
    assert blanks(*pair(dpi, [disc(8.0, 40.0, diameter)])) == BLANK


def square(x_mm: float, y_mm: float, side_mm: float) -> Hole:
    return Hole(x_mm, y_mm, side_mm, side_mm)


@pytest.mark.parametrize("dpi", FAST_DPIS)
@pytest.mark.parametrize("size", [HOLE_MAX_MM + 1.0, 10.0, 12.0], ids=str)
@pytest.mark.parametrize("shape", [disc, square], ids=["disc", "square"])
@pytest.mark.parametrize("corner", [(2.0, 2.0), (4.0, 4.0)], ids=str)
def test_a_disc_or_square_over_the_punched_size_in_a_corner_is_never_a_hole(
    dpi: int, size: float, shape: Callable[[float, float, float], Hole], corner: tuple[float, float]
) -> None:
    """A grey blot of 9 to 12 mm at the same corner of both sides keeps the back: a punched hole
    is no longer than ``HOLE_MAX_MM``, whatever the mark opposite. The 5 mm blank margin clips the
    part of the blot that is counted to under ``HOLE_MAX_MM``, so only the size of its whole shape
    (``_hole_sized``) keeps the page."""
    assert blanks(*pair(dpi, [shape(*corner, size)])) == KEPT


@pytest.mark.parametrize("dpi", FAST_DPIS)
@pytest.mark.parametrize("length", [STAPLE_MAX_MM - 0.1, STAPLE_MAX_MM + 0.3], ids=str)
def test_a_dash_is_a_hole_up_to_the_staple_size_and_not_over(dpi: int, length: float) -> None:
    assert blanks(*pair(dpi, [dash(12.0, 8.0, length)])) == (length < STAPLE_MAX_MM,) * 2


@pytest.mark.parametrize("dpi", FAST_DPIS)
@pytest.mark.parametrize(
    "mark",
    [
        disc(12.0, 8.0, 2.5),
        disc(12.0, 8.0, PUNCH_MIN_MM - 0.5),
        dash(12.0, 8.0, 2.5, 0.7),
        dash(12.0, 8.0, 3.2, 1.6),
    ],
    ids=["disc 2.5", "disc 3.5", "dash 2.5", "dash 3.2"],
)
def test_a_mark_between_a_staple_hole_and_a_punched_one_is_never_a_hole(
    dpi: int, mark: Hole
) -> None:
    """The size of a printed digit, a full stop in a large type or a grey blot."""
    assert blanks(*pair(dpi, [mark])) == KEPT


@pytest.mark.parametrize("dpi", FAST_DPIS)
@pytest.mark.parametrize(
    ("mark", "blank"),
    [
        (dash(8.0, 40.0, 6.0, 0.7), False),
        (dash(8.0, 40.0, 6.0, 2.0), False),
        (Hole(8.0, 40.0, 6.0, 4.2, round=True), False),
        (Hole(8.0, 40.0, 6.0, 5.4, round=True), True),
    ],
    ids=["dash", "bar", "oval", "nearly round"],
)
def test_a_mark_of_the_punched_size_is_a_hole_only_when_it_is_round(
    dpi: int, mark: Hole, blank: bool
) -> None:
    assert blanks(*pair(dpi, [mark])) == (blank, blank)


@pytest.mark.parametrize("dpi", FAST_DPIS)
@pytest.mark.parametrize(
    "mark",
    [ring(12.0, 8.0, 2.5, 0.5), ring(12.0, 8.0, 5.0, 1.0)],
    ids=["an o of 2.5 mm", "a ring of 5 mm"],
)
def test_a_ring_is_not_a_hole(dpi: int, mark: Hole) -> None:
    """A hollow mark: a "0" or an "o" of print, or the ring a cup leaves; a punched hole is a
    filled disc."""
    assert blanks(*pair(dpi, [mark])) == KEPT


@pytest.mark.parametrize("dpi", FAST_DPIS)
def test_the_other_side_is_judged_by_its_size_too(dpi: int) -> None:
    """A staple-sized mark whose twin opposite is 40 % longer (inside the size ratio, and
    overlapping it by 0.7) but over the staple size: a blot, not the other end of a hole."""
    small, big = dash(12.0, 8.0, 1.5), dash(12.0, 8.0, 2.1)
    assert blanks(*pair(dpi, [small], other=[big])) == KEPT
    assert blanks(*pair(dpi, [big], other=[small])) == KEPT
