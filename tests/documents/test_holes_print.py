"""Print is never a hole: a page number, a note or a stamp keeps its page, whatever lies at the
mirrored spot of the other side. Real holes are grey (darkest 89 to 106) and print is black (0 to
12), pen about 30."""

import pytest

from fastfoto_linux.documents.holes import HOLE_DARKEST_MIN
from tests.doc_synth import INK_TONE, Scene, paper_scene
from tests.doc_synth_holes import SMALL_MM, STAPLES, disc, holes_painter, sheet
from tests.documents.holes_helpers import DPIS, blanks, mirrored
from tests.documents.holes_print import (
    BUNDLED,
    FONTS,
    body_text,
    page_numbers,
    pen_note,
    width_mm,
    with_ghost,
)

KEPT = (False, False)
PAIRS = [(5, 6), (8, 9), (15, 16), (35, 36), (95, 96)]


def numbered(  # noqa: PLR0913
    front: int, back: int, *, dpi: int, font: str, points: float, where: str = "centre"
) -> tuple[Scene, Scene]:
    """A sheet whose front has text and a page number and whose back has only its number."""
    on_front, on_back = page_numbers(
        str(front), str(back), points=points, dpi=dpi, font=font, where=where
    )
    return sheet(dpi, [body_text(front, font=font), on_front], [on_back], seed=front)


@pytest.mark.parametrize("dpi", [200, 300])
@pytest.mark.parametrize("font", FONTS)
@pytest.mark.parametrize(("front", "back"), PAIRS, ids=str)
def test_a_back_with_only_a_page_number_is_kept_beside_the_fronts_number(
    front: int, back: int, font: str, dpi: int
) -> None:
    """At the centre of the foot, the page numbers of both sides lie at the mirrored spot and the
    digits are alike enough to overlap: 5 and 6, 8 and 9, 15 and 16 ..."""
    assert blanks(*numbered(front, back, dpi=dpi, font=font, points=10)) == KEPT


@pytest.mark.parametrize(("front", "back"), PAIRS, ids=str)
@pytest.mark.parametrize("points", [9, 12])
def test_numbers_at_the_outer_corners_are_kept_too(front: int, back: int, points: int) -> None:
    """The right corner of the front and the left corner of the back are one spot."""
    sides = numbered(front, back, dpi=200, font=BUNDLED, points=points, where="outer")
    assert blanks(*sides) == KEPT


@pytest.mark.parametrize("start", range(1, 10))
def test_no_back_of_a_numbered_document_is_dropped_for_its_number(start: int) -> None:
    """A sample of the pages 1 and 2 to 99 and 100: every size and place, in turn."""
    dropped = []
    for index, front in enumerate(range(start, 100, 9)):
        points, where = 9 + (front + index) % 4, ("centre", "outer")[index % 2]
        sides = numbered(front, front + 1, dpi=200, font=BUNDLED, points=points, where=where)
        if blanks(*sides)[1]:
            dropped.append(front + 1)
    assert dropped == []


# One glyph of a pen note near an edge of the back, against dense text on the front. Each was
# taken for a hole by its chance resemblance to the text opposite (the side, the glyph, the type
# size, the distance from the edge and the baseline, in mm).
NOTES = [
    ("left", "b", 10, 17.3, 90.9),
    ("right", "q", 11, 19.7, 17.8),
    ("right", "e", 11, 14.9, 16.7),
    ("left", "p", 12, 10.2, 90.5),
    ("right", "e", 10, 17.4, 76.4),
    ("right", "p", 12, 15.4, 23.4),
    ("right", "Y", 10, 16.3, 66.0),
    ("right", "l", 11, 14.7, 41.1),
]


@pytest.mark.parametrize(("side", "glyph", "points", "edge", "baseline"), NOTES)
def test_a_one_glyph_pen_note_against_dense_text_is_kept(
    side: str, glyph: str, points: int, edge: float, baseline: float
) -> None:
    x = edge if side == "left" else SMALL_MM[0] - edge - width_mm(glyph, points, 200)
    note = pen_note(glyph, x, baseline, points, BUNDLED)
    front, back = sheet(200, [body_text(1, points=points)], [note], seed=3)
    assert blanks(front, back)[1] is False


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize("darkest", [150, 158])
def test_a_dark_stamp_is_not_dropped_for_its_ghost_on_the_back(dpi: int, darkest: int) -> None:
    """The front holds only a 7 mm stamp in black ink, the back its show-through, darkest 150 to
    160: a ghost is a lighter picture of a stamp, not the stamp's own hole."""
    stamp = holes_painter([disc(84.0, 10.0, 7.0)], tone=INK_TONE)
    source = stamp(paper_scene(dpi=dpi, paper_mm=SMALL_MM, seed=4))
    front, back = sheet(
        dpi, [stamp], [lambda scene: with_ghost(scene, source, darkest=darkest)], seed=4
    )
    assert blanks(front, back)[0] is False


@pytest.mark.parametrize("dpi", DPIS)
@pytest.mark.parametrize("tone", [INK_TONE, HOLE_DARKEST_MIN - 20])
def test_holes_as_dark_as_ink_are_marks_on_both_sides(dpi: int, tone: int) -> None:
    """The same shapes at the mirrored spots, but black: print, never the backing seen through
    the paper."""
    front, back = sheet(
        dpi, [holes_painter(STAPLES, tone)], [holes_painter(mirrored(STAPLES), tone)]
    )
    assert blanks(front, back) == KEPT


@pytest.mark.parametrize("dpi", DPIS)
def test_holes_a_little_lighter_than_the_limit_are_holes_on_both_sides(dpi: int) -> None:
    tone = HOLE_DARKEST_MIN + 15
    front, back = sheet(
        dpi, [holes_painter(STAPLES, tone)], [holes_painter(mirrored(STAPLES), tone)]
    )
    assert blanks(front, back) == (True, True)
