"""No cut removes anything that is neither blank white nor the scanner's backing.

The tail is judged in the columns that are white in the last 2 mm, but the cut applies to every
column: a pale slip or sticky note that hangs below the end of the paper is not in the columns
that were judged. The last check on each strip a trim would remove says no when the strip holds a
cluster that is neither near the tail's white nor backing.
"""

from dataclasses import replace

import cv2
import numpy as np
import pytest

from fastfoto_linux.documents.trim import Trimmed, trim_page
from tests.doc_synth import BACKING_RGB, LETTER_MM, Scene, paper_scene, with_text, with_tinted_block
from tests.documents.helpers import colour_page, grey_page
from tests.documents.trim_helpers import DPI, RECEIPT_MM, mm, receipt

FRAME_MM = (LETTER_MM[0], 297.0)  # the scanner's frame is longer than Letter
GREEN = (70, 100, 60)
SLIP_X_MM = 90.0
SLIP_TOP_MM = 270.0  # starts inside the paper and runs down to the frame's end
PENCIL_Y_MM = 284.0  # below the end of the paper (279.4 mm)
STROKES = 5
STROKE_STEP_MM = 3.0
STROKE_SIZE_MM = (0.6, 3.0)
SLIPS = {
    "pale-blue": (200, 220, 255),
    "cream": (240, 230, 210),
    "white-ish": (248, 248, 248),
    "yellow": (255, 250, 170),
}


def slip_scene(slip: tuple[int, int, int], width_mm: float, *, pencil: int | None) -> Scene:
    """A page with a photo, and a slip hanging below the paper with strokes ``pencil`` levels
    darker than the slip (None: no strokes)."""
    scene = paper_scene(dpi=DPI, scan_mm=FRAME_MM, noise=0)
    scene = with_tinted_block(scene, 10.0, 20.0, (195.0, 80.0), GREEN)
    scene = with_tinted_block(
        scene, SLIP_X_MM, SLIP_TOP_MM, (width_mm, FRAME_MM[1] - SLIP_TOP_MM), slip
    )
    if pencil is None:
        return scene
    pen = tuple(max(0, channel - pencil) for channel in slip)
    for index in range(STROKES):
        x_mm = SLIP_X_MM + 2.0 + index * STROKE_STEP_MM
        scene = with_tinted_block(scene, x_mm, PENCIL_Y_MM, STROKE_SIZE_MM, pen)
    return scene


def changed_pixels_cut_off(result: Trimmed, drawn: np.ndarray, plain: np.ndarray) -> int:
    """How many pixels that differ between ``drawn`` and ``plain`` lie in what the trim removed."""
    differs = np.any(drawn != plain, axis=2)
    height, width = differs.shape
    cut = differs[height - result.bottom :].sum() if result.bottom else 0
    cut += differs[:, : result.left].sum() + (
        differs[:, width - result.right :].sum() if result.right else 0
    )
    return int(cut)


@pytest.mark.parametrize("make", [colour_page, grey_page], ids=["colour", "grey"])
@pytest.mark.parametrize("pencil", [15, 25, 40])
@pytest.mark.parametrize("width_mm", [15.0, 40.0])
@pytest.mark.parametrize("name", list(SLIPS))
def test_pencil_on_a_pale_slip_hanging_below_the_paper_is_never_cut(
    name: str, width_mm: float, pencil: int, make
) -> None:
    drawn = slip_scene(SLIPS[name], width_mm, pencil=pencil)
    plain = slip_scene(SLIPS[name], width_mm, pencil=None)
    result = trim_page(make(drawn))
    cut = changed_pixels_cut_off(result, drawn.image, plain.image)
    assert cut == 0


def test_the_same_page_without_the_slip_still_loses_its_tail() -> None:
    scene = with_tinted_block(
        paper_scene(dpi=DPI, scan_mm=FRAME_MM, noise=0), 10.0, 20.0, (195.0, 80.0), GREEN
    )
    result = trim_page(colour_page(scene))
    assert scene.paper_end <= result.page.pixels.shape[0] <= scene.paper_end + mm(3) + 1


def test_a_small_note_lying_in_the_backing_strip_keeps_that_strip() -> None:
    """1.5 mm of the 200 mm above the tail is under the 1% of its rows a backing column may
    differ in, so the strip is found, and the note in it is what the last check sees."""
    scene = receipt(offset_mm=60.0)
    note = with_tinted_block(scene, -40.0, 100.0, (1.5, 1.5), (240, 230, 210))
    result = trim_page(colour_page(note))
    assert result.left == 0
    assert result.right > 0  # the other strip is plain backing and still goes


def test_a_dust_speck_in_the_backing_strip_does_not_keep_it() -> None:
    scene = receipt(offset_mm=60.0)
    speck = with_tinted_block(scene, -40.0, 100.0, (0.2, 0.2), (240, 230, 210))
    result = trim_page(colour_page(speck))
    assert abs(result.left - scene.paper_x[0]) <= 1


def soften(scene: Scene) -> np.ndarray:
    """The scan as a blurred sensor would give it: every edge spreads over a pixel or two."""
    return cv2.blur(scene.image, (3, 3))


@pytest.mark.parametrize("make", [colour_page, grey_page], ids=["colour", "grey"])
def test_the_soft_edge_between_backing_and_the_tail_does_not_stop_the_tail_cut(make) -> None:
    """Pixels where the backing and the white blend are neither, but they are no content."""
    scene = receipt(offset_mm=60.0)
    page = make(replace(scene, image=soften(scene)))
    result = trim_page(page)
    assert result.bottom > 0
    assert result.page.pixels.shape[0] <= scene.paper_end + mm(6)


@pytest.mark.parametrize("shift", [-12, -6, 6, 12])
def test_a_grey_receipt_on_backing_a_little_off_the_measured_grey_still_loses_its_tail(
    shift: int,
) -> None:
    """On a grey page the backing is the measured colour's grey within the same distance."""
    backing = tuple(channel + shift for channel in BACKING_RGB)
    scene = paper_scene(
        dpi=DPI, paper_mm=RECEIPT_MM, scan_mm=LETTER_MM, offset_mm=60.0, backing=backing
    )
    for row in range(8):
        scene = with_text(scene, 6, 10 + row * 20, 10)
    result = trim_page(grey_page(scene))
    assert scene.paper_end <= result.page.pixels.shape[0] <= scene.paper_end + mm(5)
