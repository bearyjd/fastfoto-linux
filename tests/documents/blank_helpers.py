"""Pages and verdicts shared by the blank-page tests (creases, faint writing, dust)."""

from fastfoto_linux.documents.blank import BLANK_MARGIN_MM, is_blank
from fastfoto_linux.documents.marks import Mark, find_marks
from tests.doc_synth import Scene, paper_scene
from tests.doc_synth_creases import with_line
from tests.documents.helpers import bw_page, colour_page, grey_page

DPIS = [200, 300, 600]
SMALL_MM = (100.0, 120.0)  # creases at 40 and 80 mm; small so that 600 dpi stays fast
TALL_MM = (100.0, 230.0)  # tall enough for a 153 mm artefact
FAINT_BAR_TONE = 160
PAGE_OF = {"colour": colour_page, "grey": grey_page, "bw": bw_page}
# A 1-bit page turns every tone lighter than 128 white, so faint things are judged on colour and
# grey pages only; ink darker than 128 is judged on the 1-bit page too.
BLANK = {"colour": True, "grey": True}
KEPT = {"colour": False, "grey": False}
KEPT_ALSO_IN_1_BIT = {"colour": False, "grey": False, "bw": False}


def sheet(dpi: int, paper_mm: tuple[float, float] = SMALL_MM, **kwargs) -> Scene:
    return paper_scene(dpi=dpi, paper_mm=paper_mm, **kwargs)


def verdicts(scene: Scene, *, one_bit: bool = False) -> dict[str, bool]:
    """Whether the scene is blank as a colour page and as a grey one (and as a 1-bit one)."""
    kinds = list(PAGE_OF) if one_bit else ["colour", "grey"]
    return {kind: is_blank(PAGE_OF[kind](scene)) for kind in kinds}


def marks_of(scene: Scene) -> tuple[Mark, ...]:
    """The marks the plain detector finds inside the blank rule's margin."""
    return find_marks(colour_page(scene), margin_mm=BLANK_MARGIN_MM)


def bar(dpi: int, thickness_mm: float, length_mm: float, tone: int = FAINT_BAR_TONE) -> Scene:
    """A horizontal bar of the given size on an empty sheet, well inside the margin."""
    return with_line(
        sheet(dpi), (30.0, 60.0), (30.0 + length_mm, 60.0), tone=tone, thickness_mm=thickness_mm
    )
