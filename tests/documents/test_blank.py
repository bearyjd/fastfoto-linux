"""Blank-page detection is conservative: one confident mark keeps the page."""

import numpy as np
import pytest

from fastfoto_linux.documents.blank import is_blank
from fastfoto_linux.documents.loader import LoadedPage
from fastfoto_linux.documents.marks import find_marks
from fastfoto_linux.documents.modes import ColourMode
from tests.doc_synth import (
    LETTER_MM,
    LIGHT_PENCIL_TONE,
    PENCIL_TONE,
    Scene,
    paper_scene,
    with_show_through,
    with_signature,
    with_solid_block,
    with_specks,
    with_text,
    with_tinted_block,
)
from tests.documents.helpers import bw_page, colour_page, grey_page, pages_of

DPI = 100
KINDS = ["colour", "grey", "bw"]


def sheet(dpi: int = DPI, **kwargs) -> Scene:
    return paper_scene(dpi=dpi, **kwargs)


def verdicts(scene: Scene) -> dict[str, bool]:
    return {kind: is_blank(page) for kind, page in pages_of(scene).items()}


# ---- pages that are blank ------------------------------------------------------------------


def test_empty_paper_is_blank_in_every_kind_of_page() -> None:
    assert verdicts(sheet()) == dict.fromkeys(KINDS, True)


def test_coarse_paper_texture_is_blank() -> None:
    assert verdicts(sheet(noise=8)) == dict.fromkeys(KINDS, True)


def test_dust_specks_are_blank() -> None:
    assert verdicts(with_specks(sheet(), 120, max_px=3)) == dict.fromkeys(KINDS, True)


def test_faint_mirrored_show_through_is_blank() -> None:
    front = with_text(sheet(), 25, 40, 40)
    for row in range(8):
        front = with_text(front, 25, 50 + row * 9, 40)
    back = with_show_through(sheet(seed=5), front, peak=30)
    assert back.image.min() < 240 - 10  # the ghost really is in the paper
    assert is_blank(colour_page(back))
    assert is_blank(grey_page(back))


def test_text_inside_the_5_mm_margin_does_not_count() -> None:
    scene = with_text(sheet(), 0.5, 0.5, 3)  # top left corner
    scene = with_text(scene, 100, LETTER_MM[1] - 4.0, 3)  # bottom edge
    assert verdicts(scene) == dict.fromkeys(KINDS, True)


def test_a_one_bit_page_with_only_specks_is_blank() -> None:
    assert is_blank(bw_page(with_specks(sheet(), 120, max_px=3)))


# ---- pages that are not blank --------------------------------------------------------------


def test_one_short_line_of_text_keeps_the_page() -> None:
    assert verdicts(with_text(sheet(), 30, 100, 6)) == dict.fromkeys(KINDS, False)


def test_a_page_number_alone_keeps_the_page() -> None:
    """Decided and documented: a lone digit is indistinguishable from content, so keep it."""
    scene = with_text(sheet(), LETTER_MM[0] / 2, LETTER_MM[1] - 15.0, 1)
    assert verdicts(scene) == dict.fromkeys(KINDS, False)


def test_a_signature_alone_keeps_the_page() -> None:
    assert verdicts(with_signature(sheet(), 60, 200)) == dict.fromkeys(KINDS, False)


def test_a_light_pencil_note_with_clear_contrast_keeps_the_page() -> None:
    scene = with_text(sheet(), 30, 100, 10, tone=PENCIL_TONE)
    assert is_blank(colour_page(scene)) is False
    assert is_blank(grey_page(scene)) is False


def test_a_lighter_pencil_note_only_60_levels_darker_than_the_paper_still_counts() -> None:
    scene = with_text(sheet(), 30, 100, 10, tone=LIGHT_PENCIL_TONE)
    assert is_blank(colour_page(scene)) is False
    assert is_blank(grey_page(scene)) is False


def test_text_just_outside_the_margin_counts() -> None:
    assert verdicts(with_text(sheet(), 8, 8, 3)) == dict.fromkeys(KINDS, False)


def test_a_large_flat_grey_block_keeps_the_page() -> None:
    scene = with_solid_block(sheet(), 60, 80, 40, tone=150)
    assert is_blank(colour_page(scene)) is False
    assert is_blank(grey_page(scene)) is False


def test_a_yellow_highlighter_stripe_keeps_the_page() -> None:
    scene = with_tinted_block(sheet(), 40, 100, (80.0, 6.0), (255, 250, 120))
    assert is_blank(colour_page(scene)) is False


def test_a_black_page_is_not_blank() -> None:
    page = LoadedPage(np.zeros((300, 200), np.uint8), ColourMode.GREY, DPI)
    assert is_blank(page) is False


def test_a_signature_among_specks_and_texture_still_keeps_the_page() -> None:
    scene = with_signature(with_specks(sheet(noise=6), 100), 60, 200)
    assert verdicts(scene) == dict.fromkeys(KINDS, False)


@pytest.mark.parametrize("dpi", [100, 150, 300])
def test_the_verdicts_hold_at_every_resolution(dpi: int) -> None:
    blank = with_specks(sheet(dpi), 150, max_px=max(1, dpi // 40))
    text = with_text(sheet(dpi), 30, 100, 6)
    assert is_blank(colour_page(blank)) is True
    assert is_blank(colour_page(text)) is False


def test_blank_detection_does_not_modify_the_page() -> None:
    page = colour_page(with_text(sheet(), 30, 100, 6))
    before = page.pixels.copy()
    is_blank(page)
    assert np.array_equal(page.pixels, before)


# ---- the marks themselves ------------------------------------------------------------------


def test_each_glyph_of_a_line_is_one_mark_at_its_place() -> None:
    scene = with_text(sheet(), 30, 100, 5)
    marks = find_marks(colour_page(scene))
    assert len(marks) == 5
    assert scene.content is not None
    for mark in marks:
        assert scene.content[0] - 1 <= mark.x0 < mark.x1 <= scene.content[2] + 1
        assert scene.content[1] - 1 <= mark.y0 < mark.y1 <= scene.content[3] + 1


def test_marks_are_in_page_pixels_at_any_resolution() -> None:
    scene = with_text(sheet(300), 30, 100, 4)
    marks = find_marks(colour_page(scene))
    assert len(marks) == 4
    assert scene.content is not None
    assert min(m.x0 for m in marks) == pytest.approx(scene.content[0], abs=3)
    assert max(m.x1 for m in marks) == pytest.approx(scene.content[2], abs=3)
    assert min(m.y0 for m in marks) == pytest.approx(scene.content[1], abs=3)
    assert max(m.y1 for m in marks) == pytest.approx(scene.content[3], abs=3)


def test_specks_and_texture_are_not_marks() -> None:
    assert find_marks(colour_page(with_specks(sheet(noise=6), 150))) == ()


def test_the_margin_argument_leaves_out_marks_outside_it() -> None:
    scene = with_text(sheet(), 2, 2, 2)
    scene = with_text(scene, 100, 100, 2)
    page = colour_page(scene)
    assert len(find_marks(page)) == 4
    assert len(find_marks(page, margin_mm=5.0)) == 2
