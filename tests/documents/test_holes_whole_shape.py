"""A hole is judged by its whole dark shape, joined up the way the eye does it: a stroke that
nearly touches it makes it content, and a one-pixel diagonal is one shape and not a dotted line."""

from dataclasses import replace

import pytest

from tests.doc_synth import INK_TONE
from tests.doc_synth_holes import HOLE_TONE, dash, holes_painter, sheet, slanted
from tests.documents.holes_helpers import PAPER_WIDTH_MM, blanks, mirrored


@pytest.mark.parametrize("tone", [INK_TONE, HOLE_TONE], ids=["ink", "grey"])
@pytest.mark.parametrize("gap", [0.10, 0.25], ids=str)
def test_a_stroke_beside_a_hole_on_the_back_alone_makes_it_content(tone: int, gap: float) -> None:
    """At 600 dpi the 4 mm stroke is a dark shape of its own, 0.1 to 0.25 mm below the hole, yet
    the two are one mark: the hole alone would match the front's, and the stroke is writing."""
    hole = dash(12.0, 8.0, 1.8, 0.7)
    mirror = hole.mirrored(PAPER_WIDTH_MM)
    stroke = dash(mirror.x_mm, mirror.y_mm + 0.7 + gap, 4.0, 0.5)
    front, back = sheet(
        600, [holes_painter([hole])], [holes_painter([mirror]), holes_painter([stroke], tone)]
    )
    assert blanks(front, back)[1] is False


@pytest.mark.parametrize("dpi", [200, 300])
@pytest.mark.parametrize("slope", [1, -1], ids=["slash", "backslash"])
@pytest.mark.parametrize("stroke_mm", [0.08, 0.12], ids=str)
def test_a_one_pixel_diagonal_hole_is_one_shape(dpi: int, slope: int, stroke_mm: float) -> None:
    """Its pixels touch only by their corners (8-connected): in 4-connected pieces nothing on the
    front would match the back's."""
    hole = [replace(slanted(12.0, 8.0, 1.5, slope), stroke_mm=stroke_mm)]
    front, back = sheet(dpi, [holes_painter(hole)], [holes_painter(mirrored(hole))], seed=4)
    assert blanks(front, back) == (True, True)
