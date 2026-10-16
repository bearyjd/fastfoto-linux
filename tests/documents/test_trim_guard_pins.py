"""Pins on two details of the last check that no other test depends on.

* Only a blurred edge between white and backing is within 2 pixels of both and no content: a wide
  slip or stroke that merely lies near the backing, with white beside it, is content.
* "Blank white" is measured from the tail's own white, not from pure white: paper a few levels
  darker than a tail of 250 is blank white, though it is 12 or more levels darker than 255.
"""

from dataclasses import replace

import pytest

from fastfoto_linux.documents.trim import trim_page
from tests.doc_synth import LEGAL_MM, LETTER_MM, paper_scene, with_tinted_block
from tests.documents.helpers import colour_page, grey_page
from tests.documents.trim_helpers import DPI, letter_text, mm, receipt

NEAR_BACKING_MM = 5.0  # from the receipt's edge: 20 px at 100 dpi, far more than a blur's 2
STROKE_MM = (8.0, 100.0)  # hangs from inside the receipt down past the end of the frame
STROKE_TOP_MM = 190.0  # the receipt is 200 mm long
STROKES = {"pale-blue": (200, 220, 255), "dark": (60, 60, 60)}
DULL_TAIL_TONE = 250  # the least that is still the scanner's white
PATCH_TONE = 242  # 8 below the tail: blank white, though 13 below 255
PATCH_COLUMNS_MM = (100.0, 108.0)  # narrow enough not to darken a twentieth of any row
PATCH_TOP_MM = 10.0  # below the end of the paper


@pytest.mark.parametrize("stroke", list(STROKES))
def test_a_wide_stroke_near_the_backing_with_white_beside_it_is_content(stroke: str) -> None:
    """On a grey page the backing beside the receipt stays in the strip that is judged."""
    scene = with_tinted_block(receipt(), NEAR_BACKING_MM, STROKE_TOP_MM, STROKE_MM, STROKES[stroke])
    result = trim_page(grey_page(scene))
    assert result.bottom == 0


def test_paper_a_few_levels_darker_than_a_dull_tail_is_blank_white() -> None:
    scene = paper_scene(
        dpi=DPI, paper_mm=LETTER_MM, scan_mm=LEGAL_MM, noise=0, tail_tone=DULL_TAIL_TONE
    )
    scene = letter_text(scene)
    image = scene.image.copy()
    left, right = (mm(x) for x in PATCH_COLUMNS_MM)
    image[scene.paper_end + mm(PATCH_TOP_MM) :, left:right] = PATCH_TONE  # down to the frame's end
    result = trim_page(colour_page(replace(scene, image=image)))
    assert result.page.pixels.shape[0] <= scene.paper_end + mm(5)
