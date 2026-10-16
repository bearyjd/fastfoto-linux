"""The backing strip is the scanner's own colour, measured above the tail, and nothing else."""

import pytest

from fastfoto_linux.documents import trim
from fastfoto_linux.documents.trim import trim_page
from fastfoto_linux.pipeline import crop
from tests.doc_synth import (
    BACKING_RGB,
    LETTER_MM,
    Scene,
    paper_scene,
    with_full_width_tail,
    with_text,
    with_tinted_block,
)
from tests.documents.helpers import colour_page
from tests.documents.trim_helpers import (
    DPI,
    RECEIPT_MM,
    assert_contains_content,
    letter_text,
    mm,
    receipt,
)

SIDEBAR_MM = 30.0
MIN_TAIL_MM = 4.0  # a shorter tail is never cut
# Blue-greys that a form may print down one edge: none is the scanner's backing colour.
PRINTED_SIDEBARS = [(140, 160, 185), (100, 120, 150), (40, 60, 110)]


def sidebar_page(colour: tuple[int, int, int], side: str, tail_mm: float) -> Scene:
    """A Letter page with a full-height printed sidebar (white text inside) and a tail below."""
    scene = paper_scene(dpi=DPI, scan_mm=(LETTER_MM[0], LETTER_MM[1] + tail_mm))
    for row in range(6):
        scene = with_text(scene, 40, 30 + row * 8, 30)
    x_mm = 0.0 if side == "left" else LETTER_MM[0] - SIDEBAR_MM
    scene = with_tinted_block(scene, x_mm, 0, (SIDEBAR_MM, LETTER_MM[1]), colour)
    return with_text(scene, x_mm + 3, 100, 4, tone=255)


@pytest.mark.parametrize("tail_mm", [0.0, 2.0, 5.0])
@pytest.mark.parametrize("side", ["left", "right"])
@pytest.mark.parametrize("colour", PRINTED_SIDEBARS, ids=str)
def test_a_printed_full_height_sidebar_is_never_cut(
    colour: tuple[int, int, int], side: str, tail_mm: float
) -> None:
    scene = sidebar_page(colour, side, tail_mm)
    result = trim_page(colour_page(scene))
    assert (result.left, result.right) == (0, 0)
    assert result.page.pixels.shape[0] >= scene.paper_end  # every row of paper stays
    if tail_mm < MIN_TAIL_MM:
        assert result.bottom == 0  # too short a tail to cut: nothing at all is cut


@pytest.mark.parametrize("offset_mm", [0.0, 60.0, 135.9], ids=["left", "centre", "right"])
def test_a_receipt_with_a_tail_that_is_white_across_the_whole_width_still_loses_its_backing(
    offset_mm: float,
) -> None:
    scene = with_full_width_tail(receipt(offset_mm=offset_mm))
    result = trim_page(colour_page(scene))
    paper_x0, paper_x1 = scene.paper_x
    assert abs(result.left - paper_x0) <= 1
    assert abs(result.right - (scene.width - paper_x1)) <= 1
    assert scene.paper_end <= result.page.pixels.shape[0] <= scene.paper_end + mm(5)
    assert_contains_content(scene, result, margin_px=mm(5))


@pytest.mark.parametrize("shift", [(-8, 0, 8), (5, -6, 4), (0, -10, 10), (3, 3, 3)], ids=str)
def test_backing_within_the_scanner_tolerance_is_recognised(shift: tuple[int, int, int]) -> None:
    backing = tuple(channel + delta for channel, delta in zip(BACKING_RGB, shift, strict=True))
    scene = paper_scene(
        dpi=DPI, paper_mm=RECEIPT_MM, scan_mm=LETTER_MM, offset_mm=60.0, backing=backing
    )
    scene = with_text(scene, 6, 10, 10)
    result = trim_page(colour_page(scene))
    assert abs(result.left - scene.paper_x[0]) <= 1
    assert abs(result.right - (scene.width - scene.paper_x[1])) <= 1


@pytest.mark.parametrize(
    "backing",
    [(172, 210, 219), (202, 180, 219), (202, 210, 245), (230, 238, 247), (210, 210, 210)],
    ids=str,
)
def test_blue_grey_beyond_the_scanner_tolerance_is_not_backing(
    backing: tuple[int, int, int],
) -> None:
    scene = paper_scene(
        dpi=DPI, paper_mm=RECEIPT_MM, scan_mm=LETTER_MM, offset_mm=60.0, backing=backing
    )
    result = trim_page(colour_page(with_text(scene, 6, 10, 10)))
    assert (result.left, result.right) == (0, 0)


def test_a_full_height_sidebar_within_the_backing_tolerance_is_trimmed_known_limit() -> None:
    """Documented (README, design doc): a sidebar printed edge to edge, full height, in a
    blue-grey within 20 levels (RGB distance) of the backing and clearly darker than the paper
    beside it cannot be told from backing and is cut."""
    pale_blue = (190, 200, 210)  # distance 18 from the backing colour
    scene = letter_text(paper_scene(dpi=DPI))
    scene = with_tinted_block(scene, 0, 0, (SIDEBAR_MM, LETTER_MM[1]), pale_blue)
    result = trim_page(colour_page(scene))
    assert abs(result.left - mm(SIDEBAR_MM)) <= 1


def test_the_backing_colour_and_tolerance_are_the_photo_cropper_s_not_copies() -> None:
    assert getattr(trim, "BACKGROUND_PRIOR_RGB", None) is crop.BACKGROUND_PRIOR_RGB
    assert getattr(trim, "BACKGROUND_PRIOR_TOLERANCE", None) is crop.BACKGROUND_PRIOR_TOLERANCE


def test_a_page_that_is_not_the_scanners_backing_anywhere_is_untouched() -> None:
    scene = letter_text(paper_scene(dpi=DPI, scan_mm=(LETTER_MM[0], LETTER_MM[1] + 20.0)))
    result = trim_page(colour_page(scene))
    assert (result.left, result.right) == (0, 0)
    assert scene.paper_end <= result.page.pixels.shape[0] <= scene.paper_end + mm(5)
