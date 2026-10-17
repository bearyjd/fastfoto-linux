"""Sheets and verdicts shared by the hole tests (holes through the paper, seen from both sides)."""

from collections.abc import Sequence

from fastfoto_linux.documents.blank import is_blank_beside
from fastfoto_linux.documents.trim import Trimmed, trim_page
from tests.doc_synth import Scene, with_text
from tests.doc_synth_holes import SMALL_MM, STAPLES, Hole, holes_painter, sheet
from tests.documents.helpers import colour_page

DPIS = [200, 300, 600]
FAST_DPIS = [200, 300]  # 600 dpi costs four times as much: the tests that need it ask for DPIS
PAPER_WIDTH_MM, PAPER_HEIGHT_MM = SMALL_MM
# How far the back is off the front: the shift in mm (right, down) and the turn in degrees. The
# rule allows 2.0 mm each way; the largest displacement of a hole here is about 1.9 mm.
ALIGNMENTS = {
    "aligned": ((0.0, 0.0), 0.0),
    "offset": ((1.5, -1.0), 0.0),
    "offset and tilted": ((-0.8, 0.8), 0.4),
}


def mirrored(holes: Sequence[Hole]) -> list[Hole]:
    """The holes as the other side of the sheet shows them."""
    return [hole.mirrored(PAPER_WIDTH_MM) for hole in holes]


def trimmed_sides(front: Scene, back: Scene) -> tuple[Trimmed, Trimmed]:
    return trim_page(colour_page(front)), trim_page(colour_page(back))


def blanks(front: Scene, back: Scene) -> tuple[bool, bool]:
    """Whether the front and the back are blank, each judged beside the other."""
    first, second = trimmed_sides(front, back)
    return is_blank_beside(first, second), is_blank_beside(second, first)


STAPLED_DPI = 200


def text(scene: Scene) -> Scene:
    """A few separate letters across the middle of the page: writing that is not a hole."""
    return with_text(scene, 12.0, 50.0, 14)


def stapled_sheet(seed: int, *, text_front: bool = True) -> tuple[Scene, Scene]:
    """A sheet with a staple's holes, at 200 dpi: the front has text (unless told not to), the
    back has nothing else."""
    front = [text] if text_front else []
    return sheet(
        STAPLED_DPI,
        [*front, holes_painter(STAPLES)],
        [holes_painter(mirrored(STAPLES))],
        seed=seed,
    )
