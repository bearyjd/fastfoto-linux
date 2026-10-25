"""PageCrop, crop_box, to_units and edited_page: one transform for the preview and the PDF."""

import numpy as np
import pytest

from fastfoto_linux.documents.draft import PageEdit
from fastfoto_linux.documents.modes import ColourMode
from fastfoto_linux.documents.page_crop import (
    CROP_UNITS,
    PageCrop,
    crop_box,
    edited_page,
    to_units,
)
from fastfoto_linux.documents.units import mm_to_px
from tests.documents.crop_helpers import loaded

U = CROP_UNITS
KINDS = (ColourMode.GREY, ColourMode.COLOUR)


def test_the_units_are_ten_thousand() -> None:
    assert U == 10_000


def test_the_whole_page_is_a_crop() -> None:
    crop = PageCrop(0, 0, U, U)
    assert (crop.left, crop.top, crop.right, crop.bottom) == (0, 0, U, U)


@pytest.mark.parametrize(
    "args",
    [
        (True, 0, U, U),
        (0, False, U, U),
        (0.0, 0, U, U),
        (0, 0, float(U), U),
        (-1, 0, U, U),
        (0, 0, U + 1, U),
        (0, 0, U, U + 1),
        (5, 0, 5, U),
        (0, 5, U, 5),
        (0, 9, U, 3),
        (9, 0, 3, U),
        ("0", 0, U, U),
    ],
)
def test_a_crop_that_is_not_a_box_of_whole_units_is_refused(args: tuple) -> None:
    with pytest.raises(ValueError):
        PageCrop(*args)


def test_the_full_page_resolves_to_the_full_page() -> None:
    assert crop_box(1240, 1748, 300, PageCrop(0, 0, U, U)) == (0, 0, 1240, 1748)


def test_a_box_is_rounded_inward() -> None:
    # 3333 / 10000 of 1000 px is 333.3: the left edge moves in to 334; 6667 gives 666.7: out to 666
    assert crop_box(1000, 1000, 300, PageCrop(3333, 3333, 6667, 6667)) == (334, 334, 666, 666)


def test_a_box_given_in_pixels_comes_back_exactly_for_20000_random_boxes() -> None:
    rng = np.random.default_rng(7)
    for _ in range(20_000):
        width = int(rng.integers(100, U + 1))
        height = int(rng.integers(100, U + 1))
        left = int(rng.integers(0, width - 20))
        top = int(rng.integers(0, height - 20))
        box = (
            left,
            top,
            int(rng.integers(left + 10, width + 1)),
            int(rng.integers(top + 10, height + 1)),
        )
        # dpi 50 makes the 5 mm minimum 10 px, so no box here is grown
        assert crop_box(width, height, 50, to_units(box, width, height)) == box


@pytest.mark.parametrize("size", [1, 2, 3, 99, 100, 1240, 1748, 7016, U])
def test_the_whole_page_in_pixels_round_trips(size: int) -> None:
    crop = to_units((0, 0, size, size), size, size)
    assert crop == PageCrop(0, 0, U, U)
    assert crop_box(size, size, 300, crop) == (0, 0, size, size)


@pytest.mark.parametrize("box", [(0, 0, 0, 5), (5, 5, 5, 9), (6, 0, 5, 9), (-1, 0, 5, 5)])
def test_to_units_refuses_an_empty_box(box: tuple) -> None:
    with pytest.raises(ValueError):
        to_units(box, 100, 100)


def test_to_units_refuses_a_box_outside_the_page() -> None:
    with pytest.raises(ValueError):
        to_units((0, 0, 101, 50), 100, 100)
    with pytest.raises(ValueError):
        to_units((0, 0, 50, 101), 100, 100)


MIN_PX = mm_to_px(5, 300)  # 59


def test_a_side_under_five_mm_grows_around_its_centre() -> None:
    left, top, right, bottom = crop_box(1000, 1000, 300, PageCrop(5000, 5000, 5100, 5100))
    assert (right - left, bottom - top) == (MIN_PX, MIN_PX)  # it was 10 px
    assert abs((left + right) / 2 - 505) <= 1
    assert abs((top + bottom) / 2 - 505) <= 1


def test_a_small_side_at_the_left_edge_is_pushed_in_not_out() -> None:
    left, _, right, _ = crop_box(1000, 1000, 300, PageCrop(0, 0, 10, U))
    assert (left, right - left) == (0, MIN_PX)


def test_a_small_side_at_the_right_edge_is_pushed_in_not_out() -> None:
    left, _, right, _ = crop_box(1000, 1000, 300, PageCrop(U - 10, 0, U, U))
    assert (right, right - left) == (1000, MIN_PX)


def test_a_page_smaller_than_five_mm_keeps_the_whole_axis() -> None:
    assert crop_box(40, 30, 300, PageCrop(2000, 3000, 6000, 9000)) == (0, 0, 40, 30)


@pytest.mark.parametrize("dpi", [50, 300, 2400])
def test_it_never_raises_and_never_leaves_the_page(dpi: int) -> None:
    rng = np.random.default_rng(3)
    for _ in range(500):
        width, height = (int(v) for v in rng.integers(1, 3000, size=2))
        a, b = sorted(int(v) for v in rng.integers(0, U + 1, size=2))
        c, d = sorted(int(v) for v in rng.integers(0, U + 1, size=2))
        if a == b or c == d:
            continue
        left, top, right, bottom = crop_box(width, height, dpi, PageCrop(a, c, b, d))
        assert 0 <= left < right <= width
        assert 0 <= top < bottom <= height


@pytest.mark.parametrize("kind", KINDS)
def test_no_crop_and_no_turn_is_the_same_page(kind: ColourMode) -> None:
    page = loaded(kind)
    assert edited_page(page, PageEdit()) is page


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("turns", [0, 1, 2, 3])
@pytest.mark.parametrize("cropped", [False, True])
def test_the_edited_page_is_the_cut_page_turned_clockwise(
    kind: ColourMode, turns: int, cropped: bool
) -> None:
    page = loaded(kind)
    before = page.pixels.copy()
    height, width = page.pixels.shape[:2]
    crop = PageCrop(1000, 2000, 7000, 9000) if cropped else None
    result = edited_page(page, PageEdit(quarter_turns=turns, crop=crop))
    left, top, right, bottom = (
        crop_box(width, height, page.dpi, crop) if crop else (0, 0, width, height)
    )
    expected = np.rot90(page.pixels[top:bottom, left:right], -turns)
    assert np.array_equal(result.pixels, expected)
    assert result.pixels.shape == expected.shape
    assert result.pixels.flags["C_CONTIGUOUS"]
    assert (result.kind, result.dpi) == (page.kind, page.dpi)
    assert np.array_equal(page.pixels, before)


def test_the_markers_show_where_a_crop_cut() -> None:
    page = loaded(ColourMode.GREY)
    height, width = page.pixels.shape
    result = edited_page(page, PageEdit(crop=PageCrop(0, 0, 5000, 5000)))
    assert result.pixels[0, 0] == page.pixels[0, 0]  # the top left marker stays
    assert result.pixels.shape == (5000 * height // U, 5000 * width // U)
    assert not (result.pixels[-30:, -30:] == 220).all()  # the bottom right marker is cut away
