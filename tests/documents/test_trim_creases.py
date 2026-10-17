"""Trimming reads faint creases as marks: only the blank rule leaves them out.

A crease near the foot of the paper decides how much of the tail is kept below it, so a trim that
asked ``find_marks`` to ignore faint lines would cut closer than this.
"""

from fastfoto_linux.documents.trim import MARK_ROOM_MM, TAIL_KEEP_MM, trim_page
from tests.doc_synth import LETTER_MM, Scene, paper_scene, px, with_text
from tests.doc_synth_creases import CREASE_MM, with_line
from tests.documents.helpers import colour_page, grey_page

DPI = 200
SCAN_MM = (LETTER_MM[0], 330.0)
CREASE_ABOVE_END_MM = 1.0
CREASE_TONE = 175


def creased_foot() -> tuple[Scene, int]:
    """A page with a line of text, a faint crease 1 mm above the end of the paper, and the
    scanner's tail below; also the row after the crease."""
    scene = with_text(paper_scene(dpi=DPI, paper_mm=LETTER_MM, scan_mm=SCAN_MM), 25, 40, 30)
    y_mm = LETTER_MM[1] - CREASE_ABOVE_END_MM
    scene = with_line(scene, (40.0, y_mm), (120.0, y_mm), tone=CREASE_TONE, thickness_mm=CREASE_MM)
    return scene, px(y_mm, DPI) + max(1, px(CREASE_MM, DPI))


def test_the_crease_sets_how_much_is_kept_below_the_paper() -> None:
    scene, crease_end = creased_foot()
    kept = trim_page(colour_page(scene)).page.pixels.shape[0]
    assert kept >= crease_end + px(MARK_ROOM_MM, DPI)  # room below the crease, as for any mark
    assert kept > scene.paper_end + px(TAIL_KEEP_MM, DPI)  # more than the end of the paper needs


def test_the_tail_below_the_crease_still_goes() -> None:
    scene, _ = creased_foot()
    for make in (colour_page, grey_page):
        result = trim_page(make(scene))
        assert result.bottom > 0
        assert result.page.pixels.shape[0] < scene.image.shape[0]
