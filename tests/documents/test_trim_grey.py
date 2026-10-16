"""A grey page has no hue, so the scanner's backing and a pale slip look alike.

Only the tail below the paper is ever cut from a grey page, never a side. Its last check must not
take a pale slip or sticky note for backing, however it lies against the frame (flush with an edge
of the frame, or with the edge of a narrow receipt): a backing-grey pixel is no content only where
the backing really is, in a row that is backing across the whole width or in a column that is
backing from the top of the frame down to the strip.
"""

from dataclasses import replace

import pytest

from fastfoto_linux.documents.trim import trim_page
from tests.doc_synth import BACKING_RGB, LETTER_MM, Scene, paper_scene
from tests.documents.helpers import grey_page
from tests.documents.test_trim_guard import changed_pixels_cut_off
from tests.documents.trim_helpers import DPI, letter_text, mm, receipt

FRAME_MM = (LETTER_MM[0], 297.0)  # the scanner's frame is longer than Letter
NARROW_PAPER_MM = (80.0, 250.0)  # a receipt
NARROW_OFFSET_MM = 60.0
SLIP_WIDTH_MM = 30.0
SLIP_TOP_MM = {"page": 270.0, "receipt": 240.0}  # inside the paper, running to the frame's end
PENCIL_Y_MM = 284.0  # below the end of the paper in both
STROKES = 5
STROKE_STEP_PX = 12
STROKE_SIZE_PX = (2, 12)
TALL_SLIP_TOP_MM = 100.0
BAND_MM = 8.0
SLIPS = {
    "pale-blue": (200, 220, 255),  # 218 as grey: within 10 of the backing's grey
    "backing-like": (205, 212, 222),
}


def flush_slip(
    on: str,
    side: str,
    slip: tuple[int, int, int],
    *,
    pencil: int | None,
    top_mm: float | None = None,
) -> Scene:
    """A slip hanging below the paper, flush with the frame's edge (``on="page"``) or with the
    receipt's edge (``"receipt"``), with strokes ``pencil`` levels darker (None: no strokes)."""
    if on == "page":
        scene = paper_scene(dpi=DPI, scan_mm=FRAME_MM, noise=0)
    else:
        scene = paper_scene(
            dpi=DPI,
            paper_mm=NARROW_PAPER_MM,
            scan_mm=FRAME_MM,
            offset_mm=NARROW_OFFSET_MM,
            noise=0,
        )
    left, right = scene.paper_x
    left, right = (
        (left, left + mm(SLIP_WIDTH_MM)) if side == "left" else (right - mm(SLIP_WIDTH_MM), right)
    )
    image = scene.image.copy()
    image[mm(top_mm or SLIP_TOP_MM[on]) :, left:right] = slip
    if pencil is not None:
        pen = tuple(max(0, channel - pencil) for channel in slip)
        top = mm(PENCIL_Y_MM)
        for index in range(STROKES):
            x = left + STROKE_STEP_PX + index * STROKE_STEP_PX
            image[top : top + STROKE_SIZE_PX[1], x : x + STROKE_SIZE_PX[0]] = pen
    return replace(scene, image=image)


@pytest.mark.parametrize("pencil", [15, 25, 40])
@pytest.mark.parametrize("slip", list(SLIPS))
@pytest.mark.parametrize("side", ["left", "right"])
@pytest.mark.parametrize("on", ["page", "receipt"])
def test_pencil_on_a_slip_flush_with_an_edge_is_never_cut_from_a_grey_page(
    on: str, side: str, slip: str, pencil: int
) -> None:
    drawn = flush_slip(on, side, SLIPS[slip], pencil=pencil)
    plain = flush_slip(on, side, SLIPS[slip], pencil=None)
    result = trim_page(grey_page(drawn))
    assert changed_pixels_cut_off(result, drawn.image, plain.image) == 0
    assert (result.left, result.right) == (0, 0)


def test_a_grey_receipt_loses_its_tail_but_never_a_side() -> None:
    """The backing beside it runs the whole height of the frame: it is no content."""
    scene = receipt()
    result = trim_page(grey_page(scene))
    assert (result.left, result.right) == (0, 0)
    assert scene.paper_end <= result.page.pixels.shape[0] <= scene.paper_end + mm(5)


def test_a_grey_letter_page_with_a_backing_band_below_the_paper_still_loses_its_tail() -> None:
    scene = letter_text(paper_scene(dpi=DPI, scan_mm=FRAME_MM, noise=0))
    band_end = scene.paper_end + mm(BAND_MM)
    image = scene.image.copy()
    image[scene.paper_end : band_end] = BACKING_RGB  # across the whole width
    result = trim_page(grey_page(replace(scene, image=image)))
    assert band_end <= result.page.pixels.shape[0] <= band_end + mm(4)


@pytest.mark.parametrize("pencil", [15, 25])
@pytest.mark.parametrize("on", ["page", "receipt"])
def test_pencil_on_a_tall_slip_flush_with_an_edge_is_never_cut_from_a_grey_page(
    on: str, pencil: int
) -> None:
    """The slip is backing grey over more than half of the rows above the strip, not 99%."""
    drawn = flush_slip(on, "left", SLIPS["pale-blue"], pencil=pencil, top_mm=TALL_SLIP_TOP_MM)
    plain = flush_slip(on, "left", SLIPS["pale-blue"], pencil=None, top_mm=TALL_SLIP_TOP_MM)
    result = trim_page(grey_page(drawn))
    assert changed_pixels_cut_off(result, drawn.image, plain.image) == 0
