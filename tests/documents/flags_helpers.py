"""Pages that set (or just miss) each flag: a sheet's two sides and what is drawn on them."""

from collections.abc import Sequence
from dataclasses import replace

from fastfoto_linux.documents.assess import PageAssessment, assess_page
from fastfoto_linux.documents.trim import Trimmed, trim_page
from tests.doc_synth import INK_TONE, Scene, paper_scene, with_solid_block, with_text
from tests.doc_synth_holes import SMALL_MM, Painter, sheet
from tests.documents.helpers import colour_page

FAST_DPIS = [200, 300]
GHOST_TONE = 150  # pale, but a mark: 90 darker than the paper, and paler than 140 + the gap
FAINT_TONE = 175


def glyphs(x_mm: float, y_mm: float, chars: int, tone: int = INK_TONE) -> Painter:
    """A run of separate letters, each one a mark."""
    return lambda scene: with_text(scene, x_mm, y_mm, chars, tone=tone)


def lines(rows: int = 5, chars: int = 8, tone: int = INK_TONE) -> list[Painter]:
    """Rows of letters in the middle of the sheet: print, many marks, clear of every edge."""
    return [glyphs(30.0, 30.0 + row * 8.0, chars, tone) for row in range(rows)]


def block(x_mm: float, y_mm: float, size_mm: float) -> Painter:
    return lambda scene: with_solid_block(scene, x_mm, y_mm, size_mm, INK_TONE)


def ghost_of(
    painters: Sequence[Painter], dpi: int, tone: int = GHOST_TONE, *, upside_down: bool = False
) -> Painter:
    """The ink of ``painters`` as the other side of the paper shows it, in ``tone``: flipped left
    to right (or, for a near miss, top to bottom, where it is NOT on the other side)."""
    source = paper_scene(dpi=dpi, paper_mm=SMALL_MM)
    for paint in painters:
        source = paint(source)
    ink = source.image.min(axis=2) < INK_TONE * 2
    ink = ink[::-1, :] if upside_down else ink[:, ::-1]

    def paint_ghost(scene: Scene) -> Scene:
        image = scene.image.copy()
        image[ink] = tone
        return replace(scene, image=image)

    return paint_ghost


def trimmed_pair(front: Scene, back: Scene) -> tuple[Trimmed, Trimmed]:
    return trim_page(colour_page(front)), trim_page(colour_page(back))


def assess_sides(
    dpi: int, front: Sequence[Painter], back: Sequence[Painter], seed: int = 0
) -> tuple[PageAssessment, PageAssessment]:
    """The front and the back of one sheet, each assessed beside the other."""
    first, second = trimmed_pair(*sheet(dpi, front, back, seed=seed))
    return assess_page(first, second), assess_page(second, first)


def assess_alone(scene: Scene) -> PageAssessment:
    return assess_page(trim_page(colour_page(scene)), None)
