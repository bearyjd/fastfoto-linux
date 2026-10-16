"""A faint lone footer under solid content on very white paper is never trimmed away.

A footer is one short mark: too little of a row for the row's tone to notice, and on paper that
is only a few levels from the scanner's white the rows around it look like the tail.
"""

from collections.abc import Callable
from dataclasses import replace

import pytest

from fastfoto_linux.documents.trim import trim_page
from tests.doc_synth import (
    LEGAL_MM,
    LETTER_MM,
    Scene,
    paper_scene,
    with_solid_block,
    with_text,
    with_tinted_block,
)
from tests.documents.helpers import colour_page, grey_page
from tests.documents.trim_helpers import DPI, assert_contains_content, letter_text, mm

FOOTER_Y_MM = 268.0  # a page number near the foot of a Letter page
FOOTER_HEIGHT_MM = 2.5
ROOM_MM = 5.0  # kept below the last mark


def photo(scene: Scene) -> Scene:
    return with_solid_block(scene, 25.0, 20.0, 130.0, 100)


def table(scene: Scene) -> Scene:
    return with_tinted_block(scene, 10.0, 60.0, (195.0, 24.0), (90, 90, 90))


def white_paper(tone: int, *, scan_mm: tuple[float, float] = LETTER_MM) -> Scene:
    return paper_scene(dpi=DPI, paper_tone=tone, noise=0, tail_tone=255, scan_mm=scan_mm)


@pytest.mark.parametrize("make", [colour_page, grey_page], ids=["colour", "grey"])
@pytest.mark.parametrize("footer_tone", [225, 235])
@pytest.mark.parametrize("paper_tone", [253, 255])
@pytest.mark.parametrize("above", [photo, table], ids=["photo", "table"])
def test_a_lone_faint_footer_under_solid_content_is_kept_with_room_below_it(
    above: Callable[[Scene], Scene], paper_tone: int, footer_tone: int, make
) -> None:
    scene = with_text(above(white_paper(paper_tone)), 105.0, FOOTER_Y_MM, 1, tone=footer_tone)
    result = trim_page(make(scene))
    assert_contains_content(scene, result, margin_px=mm(ROOM_MM))


def test_the_empty_margin_between_solid_content_and_a_faint_footer_is_not_the_tail() -> None:
    scene = with_text(photo(white_paper(253)), 105.0, FOOTER_Y_MM, 1, tone=225)
    result = trim_page(colour_page(scene))
    assert result.page.pixels.shape[0] >= mm(FOOTER_Y_MM + FOOTER_HEIGHT_MM + ROOM_MM)


def test_the_empty_bottom_of_very_white_paper_still_goes_down_to_the_room_below_the_footer() -> (
    None
):
    scene = white_paper(253, scan_mm=(LETTER_MM[0], LEGAL_MM[1] - 20.0))
    scene = with_text(photo(scene), 105.0, 200.0, 1, tone=225)  # footer 200 to 202.5 mm
    result = trim_page(colour_page(scene))
    kept = result.page.pixels.shape[0]
    assert_contains_content(scene, result, margin_px=mm(ROOM_MM))
    assert kept <= mm(200.0 + FOOTER_HEIGHT_MM + ROOM_MM + 2.0)


def test_a_speck_smaller_than_a_letter_in_the_tail_does_not_stop_the_cut() -> None:
    scene = letter_text(paper_scene(dpi=DPI, paper_mm=LETTER_MM, scan_mm=LEGAL_MM))
    image = scene.image.copy()
    image[scene.paper_end + mm(40), mm(100)] = 150  # one pixel: 0.25 mm of dust
    result = trim_page(colour_page(replace(scene, image=image)))
    assert result.page.pixels.shape[0] <= scene.paper_end + mm(5)
