"""The tail is measured with a low row tone: faint footers, watermarks and white margins stay."""

import pytest

from fastfoto_linux.documents.trim import trim_page
from tests.doc_synth import LETTER_MM, Scene, paper_scene, with_text, with_tinted_block
from tests.documents.helpers import colour_page, grey_page
from tests.documents.trim_helpers import (
    DPI,
    assert_contains_content,
    mm,
    receipt,
)

HEADER_GREY = (150, 150, 150)
HEADER_MM = 40.0
FOOTER_Y_MM = 240.0
WATERMARK = (225, 225, 225)


def white_page() -> Scene:
    """Paper as white as the scanner's tail, with a grey header band and a line of body text."""
    scene = paper_scene(dpi=DPI, paper_tone=255, noise=0, tail_tone=None)
    scene = with_tinted_block(scene, 0, 0, (LETTER_MM[0], HEADER_MM), HEADER_GREY)
    return with_text(scene, 25, 100, 30)


@pytest.mark.parametrize("tone", [200, 215, 225])
@pytest.mark.parametrize("make", [colour_page, grey_page], ids=["colour", "grey"])
def test_a_faint_footer_on_very_white_paper_is_kept_with_the_margin_below_it(
    tone: int, make
) -> None:
    scene = with_text(white_page(), 25, FOOTER_Y_MM, 40, tone=tone)
    result = trim_page(make(scene))
    assert_contains_content(scene, result, margin_px=mm(3))


def test_a_faint_watermark_on_very_white_paper_is_kept() -> None:
    scene = with_tinted_block(white_page(), 40, 150, (120.0, 30.0), WATERMARK)
    result = trim_page(colour_page(scene))
    assert result.page.pixels.shape[0] >= mm(150 + 30 + 2)


def test_the_white_margin_below_the_last_line_of_very_white_paper_is_kept() -> None:
    result = trim_page(colour_page(white_page()))
    assert result.bottom == 0


@pytest.mark.parametrize("make", [colour_page, grey_page], ids=["colour", "grey"])
def test_a_faint_footer_above_a_real_tail_is_kept_and_the_tail_still_goes(make) -> None:
    scene = paper_scene(dpi=DPI, paper_mm=LETTER_MM, scan_mm=(LETTER_MM[0], 330.0))
    scene = with_text(scene, 25, 40, 30)
    scene = with_text(scene, 25, 268, 40, tone=225)  # faint, 8 mm above the end of the paper
    result = trim_page(make(scene))
    kept = result.page.pixels.shape[0]
    assert scene.paper_end <= kept <= scene.paper_end + mm(5)
    assert_contains_content(scene, result, margin_px=mm(5))


def test_a_narrow_receipt_on_a_grey_page_keeps_its_last_faint_line_with_its_whole_tail() -> None:
    scene = receipt()
    scene = with_text(scene, 6, 188, 10, tone=225)
    result = trim_page(grey_page(scene))
    assert result.bottom == 0  # a missed trim, accepted: see test_trim_grey
    assert_contains_content(scene, result, margin_px=mm(5))
