"""Trim only what is certainly empty; when unsure, trim nothing and never cut content."""

from dataclasses import replace

import numpy as np
import pytest

from fastfoto_linux.documents.modes import ColourMode
from fastfoto_linux.documents.trim import trim_page
from tests.doc_synth import (
    BACKING_RGB,
    LEGAL_MM,
    LETTER_MM,
    Scene,
    paper_scene,
    with_signature,
    with_text,
    with_tinted_block,
)
from tests.documents.helpers import bw_page, colour_page, grey_page
from tests.documents.trim_helpers import (
    DPI,
    RECEIPT_MM,
    assert_contains_content,
    letter_text,
    mm,
    receipt,
)


def test_a_full_width_letter_page_with_no_tail_is_unchanged() -> None:
    scene = letter_text(paper_scene(dpi=DPI))
    result = trim_page(colour_page(scene))
    assert (result.left, result.right, result.bottom) == (0, 0, 0)
    assert np.array_equal(result.page.pixels, scene.image)
    assert result.page.kind is ColourMode.COLOUR
    assert result.page.dpi == DPI


def test_a_legal_page_scanned_full_length_keeps_every_row() -> None:
    scene = paper_scene(dpi=DPI, paper_mm=LEGAL_MM)
    scene = with_text(letter_text(scene), 25, 335, 30)  # the last line, close to the bottom
    result = trim_page(colour_page(scene))
    assert result.bottom == 0
    assert result.page.pixels.shape == scene.image.shape


def test_the_white_tail_below_the_paper_is_cut_off() -> None:
    scene = letter_text(paper_scene(dpi=DPI, paper_mm=LETTER_MM, scan_mm=LEGAL_MM))
    result = trim_page(colour_page(scene))
    kept = result.page.pixels.shape[0]
    assert scene.paper_end + mm(2) <= kept <= scene.paper_end + mm(5)  # a little tail stays
    assert result.bottom == scene.height - kept
    assert (result.left, result.right) == (0, 0)
    assert_contains_content(scene, result, margin_px=mm(5))


def test_the_white_margin_at_the_bottom_of_the_paper_is_not_the_tail() -> None:
    """All the text is in the top third; the 180 mm of paper below it stays, tail or not."""
    scene = paper_scene(dpi=DPI, paper_mm=LETTER_MM, scan_mm=LEGAL_MM)
    scene = with_text(scene, 25, 20, 30)
    result = trim_page(colour_page(scene))
    assert result.page.pixels.shape[0] >= scene.paper_end


def test_a_tail_with_sensor_noise_is_still_recognised() -> None:
    scene = paper_scene(dpi=DPI, paper_mm=LETTER_MM, scan_mm=LEGAL_MM, tail_tone=253)
    rng = np.random.default_rng(3)
    image = scene.image.copy()
    tail = image[scene.paper_end :]
    image[scene.paper_end :] = np.clip(tail + rng.integers(-1, 2, (*tail.shape[:2], 1)), 0, 255)
    scene = letter_text(replace(scene, image=image))
    result = trim_page(colour_page(scene))
    assert result.page.pixels.shape[0] <= scene.paper_end + mm(5)


def test_a_mark_in_the_tail_is_never_cut() -> None:
    scene = paper_scene(dpi=DPI, paper_mm=LETTER_MM, scan_mm=LEGAL_MM)
    scene = with_text(letter_text(scene), 100, 300, 5)  # below the paper: dirt on the scanner
    result = trim_page(colour_page(scene))
    assert_contains_content(scene, result, margin_px=mm(5))


@pytest.mark.parametrize(
    "scene",
    [
        paper_scene(dpi=DPI, paper_tone=255, tail_tone=None, noise=0),  # all white
        paper_scene(dpi=DPI, paper_mm=LETTER_MM, scan_mm=LEGAL_MM, tail_tone=None),  # same tone
        paper_scene(  # 3 grey levels between paper and tail: too close to be certain
            dpi=DPI, paper_mm=LETTER_MM, scan_mm=LEGAL_MM, paper_tone=252, noise=0
        ),
    ],
    ids=["all-white", "tail-like-paper", "barely-different"],
)
def test_when_the_tail_cannot_be_told_from_paper_nothing_is_trimmed(scene: Scene) -> None:
    result = trim_page(colour_page(letter_text(scene)))
    assert result.bottom == 0
    assert result.page.pixels.shape == scene.image.shape


def test_a_page_that_is_almost_all_tail_keeps_the_paper_and_never_shrinks_to_nothing() -> None:
    scene = paper_scene(dpi=DPI, paper_mm=(LETTER_MM[0], 20.0), scan_mm=LETTER_MM)
    scene = with_text(scene, 25, 5, 20)
    result = trim_page(colour_page(scene))
    kept = result.page.pixels.shape[0]
    assert scene.paper_end <= kept <= scene.paper_end + mm(5)


@pytest.mark.parametrize("offset_mm", [0.0, 60.0, 135.9], ids=["left", "centre", "right"])
def test_a_narrow_receipt_loses_the_backing_beside_it_and_the_tail_below_it(
    offset_mm: float,
) -> None:
    scene = receipt(offset_mm=offset_mm)
    result = trim_page(colour_page(scene))
    paper_x0, paper_x1 = scene.paper_x
    assert abs(result.left - paper_x0) <= 1
    assert abs(result.right - (scene.width - paper_x1)) <= 1
    assert result.page.pixels.shape[1] - (paper_x1 - paper_x0) <= 2
    assert scene.paper_end <= result.page.pixels.shape[0] <= scene.paper_end + mm(5)
    assert_contains_content(scene, result, margin_px=mm(5))


@pytest.mark.parametrize("dpi", [100, 150])
def test_the_millimetres_kept_do_not_depend_on_the_resolution(dpi: int) -> None:
    result = trim_page(colour_page(receipt(dpi)))
    height, width = result.page.pixels.shape[:2]
    assert width / dpi * 25.4 == pytest.approx(RECEIPT_MM[0], abs=1.5)
    assert height / dpi * 25.4 == pytest.approx(RECEIPT_MM[1], abs=5.5)


def test_a_grey_page_has_no_hue_to_find_backing_by_so_only_the_tail_goes() -> None:
    scene = receipt()
    result = trim_page(grey_page(scene))
    assert (result.left, result.right) == (0, 0)
    assert scene.paper_end <= result.page.pixels.shape[0] <= scene.paper_end + mm(5)
    assert result.page.kind is ColourMode.GREY


def test_a_one_bit_page_is_left_alone() -> None:
    scene = receipt()
    result = trim_page(bw_page(scene))
    assert (result.left, result.right, result.bottom) == (0, 0, 0)
    assert result.page.kind is ColourMode.BW


def test_a_form_with_a_coloured_bar_across_the_top_is_not_trimmed_there() -> None:
    scene = letter_text(paper_scene(dpi=DPI))
    scene = with_tinted_block(scene, 0, 0, (LETTER_MM[0], 10.0), BACKING_RGB)
    result = trim_page(colour_page(scene))
    assert (result.left, result.right, result.bottom) == (0, 0, 0)
    assert result.page.pixels.shape == scene.image.shape


def test_a_coloured_sidebar_that_is_not_the_whole_height_is_not_backing() -> None:
    scene = letter_text(paper_scene(dpi=DPI))
    scene = with_tinted_block(scene, 0, 0, (12.0, 170.0), BACKING_RGB)
    result = trim_page(colour_page(scene))
    assert (result.left, result.right) == (0, 0)


def test_a_strip_narrower_than_a_few_millimetres_is_left_alone() -> None:
    narrow = paper_scene(
        dpi=DPI, paper_mm=(LETTER_MM[0] - 2.0, LETTER_MM[1]), scan_mm=LETTER_MM, offset_mm=2.0
    )
    result = trim_page(colour_page(letter_text(narrow)))
    assert (result.left, result.right) == (0, 0)


@pytest.mark.parametrize(
    "backing",
    [(120, 120, 120), (200, 190, 180), (0, 0, 0), (250, 250, 255)],
    ids=["neutral-grey", "warm", "black", "near-white"],
)
def test_backing_that_is_not_blue_grey_is_not_recognised(backing: tuple[int, int, int]) -> None:
    scene = paper_scene(
        dpi=DPI, paper_mm=RECEIPT_MM, scan_mm=LETTER_MM, offset_mm=60.0, backing=backing
    )
    result = trim_page(colour_page(with_text(scene, 6, 10, 10)))
    assert (result.left, result.right) == (0, 0)


def test_a_strip_beside_paper_that_is_no_brighter_is_not_backing() -> None:
    scene = paper_scene(
        dpi=DPI, paper_mm=RECEIPT_MM, scan_mm=LETTER_MM, offset_mm=60.0, paper_tone=215
    )
    result = trim_page(colour_page(with_text(scene, 6, 10, 10)))
    assert (result.left, result.right) == (0, 0)


def test_a_page_with_hardly_any_paper_left_is_not_trimmed_to_a_sliver() -> None:
    scene = paper_scene(dpi=DPI, paper_mm=(20.0, 100.0), scan_mm=LETTER_MM, offset_mm=100.0)
    result = trim_page(colour_page(scene))
    assert (result.left, result.right) == (0, 0)


def test_blue_tinted_paper_is_paper_not_backing() -> None:
    scene = letter_text(paper_scene(dpi=DPI))
    tinted = (scene.image.astype(np.float32) * np.array([0.85, 0.92, 1.0])).astype(np.uint8)
    result = trim_page(colour_page(replace(scene, image=tinted)))
    assert (result.left, result.right, result.bottom) == (0, 0, 0)


@pytest.mark.parametrize("seed", range(12))
def test_trimming_never_cuts_content(seed: int) -> None:
    """Random sheets of every size in every position: the kept area holds all the ink."""
    rng = np.random.default_rng(seed)
    width_mm = float(rng.choice([80.0, 120.0, LETTER_MM[0]]))
    length_mm = float(rng.choice([150.0, LETTER_MM[1], LEGAL_MM[1]]))
    scan_w = LETTER_MM[0]
    scan_h = float(rng.choice([length_mm, LEGAL_MM[1] + 20.0]))
    offset = float(rng.uniform(0.0, scan_w - width_mm)) if width_mm < scan_w else 0.0
    scene = paper_scene(
        dpi=DPI,
        paper_mm=(width_mm, length_mm),
        scan_mm=(scan_w, scan_h),
        offset_mm=offset,
        seed=seed,
    )
    for _ in range(int(rng.integers(1, 6))):
        x = float(rng.uniform(6.0, max(7.0, width_mm - 45.0)))
        y = float(rng.uniform(6.0, length_mm - 12.0))
        scene = with_text(scene, x, y, int(rng.integers(1, 6)))
    if width_mm > 100:
        scene = with_signature(
            scene, 10.0, float(rng.uniform(6.0, length_mm - 20.0)), width_mm=30.0
        )
    result = trim_page(colour_page(scene))
    assert_contains_content(scene, result, margin_px=mm(5))


def test_trimming_does_not_modify_its_input() -> None:
    scene = receipt()
    page = colour_page(scene)
    before = page.pixels.copy()
    trim_page(page)
    assert np.array_equal(page.pixels, before)
