"""Pins on two details of the last check that no other test depends on.

* Only a blurred edge between white and backing is within 2 pixels of both and no content: a wide
  slip or stroke that merely lies near the backing, with white beside it, is content.
* "Blank white" is measured from the tail's own white, not from pure white: paper a few levels
  darker than a tail of 250 is blank white, though it is 12 or more levels darker than 255.
"""

from dataclasses import replace

import pytest

from fastfoto_linux.documents.trim import trim_page
from tests.doc_synth import BACKING_RGB, LEGAL_MM, LETTER_MM, paper_scene, with_tinted_block
from tests.documents.helpers import colour_page, grey_page
from tests.documents.trim_helpers import DPI, RECEIPT_MM, letter_text, mm, receipt

NEAR_BACKING_MM = 2.0  # from the receipt's edge: 8 px at 100 dpi, more than a blur's 2 ...
STROKE_MM = (4.0, 100.0)  # ... and 16 px wide, so all of it is near the backing and the white
# hangs from inside the receipt down past the end of the frame
STROKE_TOP_MM = 190.0  # the receipt is 200 mm long
STROKES = {"pale-blue": (200, 220, 255), "dark": (60, 60, 60)}
DULL_TAIL_TONE = 250  # the least that is still the scanner's white
PATCH_TONE = 242  # 8 below the tail: blank white, though 13 below 255
PATCH_COLUMNS_MM = (100.0, 108.0)  # narrow enough not to darken a twentieth of any row
PATCH_TOP_MM = 10.0  # below the end of the paper
NOTE_MM = (30.0, 40.0)  # a note hanging below the paper in the backing's own colour
NOTE_SIZE_MM = (1.5, 1.5)  # a small note in the right backing strip
NOTE_X_MM = 90.0  # touching neither side of the frame
NOTE_TOP_MM = 270.0  # inside the paper, running past its end (279.4 mm) to the frame's end (297)


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


def test_a_note_of_the_backings_colour_that_touches_no_side_is_content() -> None:
    """On a colour page backing is joined to a side of the strip: a note is not."""
    scene = letter_text(paper_scene(dpi=DPI, scan_mm=(LETTER_MM[0], 297.0), noise=0))
    scene = with_tinted_block(scene, NOTE_X_MM, NOTE_TOP_MM, NOTE_MM, BACKING_RGB)
    result = trim_page(colour_page(scene))
    assert result.page.pixels.shape[0] == scene.height


def test_a_small_note_lying_in_the_right_backing_strip_keeps_that_strip() -> None:
    """The mirror of the left strip's test: both side strips are examined."""
    note = with_tinted_block(receipt(), RECEIPT_MM[0] + 40.0, 100.0, NOTE_SIZE_MM, (240, 230, 210))
    result = trim_page(colour_page(note))
    assert result.right == 0
    assert result.left > 0  # the other strip is plain backing and still goes
