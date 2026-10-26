"""What render_page allocates around despeckle: nothing page-sized for a page it will not
touch, and no 64-bit temporary for the pixels it hands back."""

import tracemalloc

import numpy as np
import pytest

from fastfoto_linux.documents import encode
from fastfoto_linux.documents.despeckle import DespeckleStatus
from fastfoto_linux.documents.encode import render_page
from fastfoto_linux.documents.loader import WHITE, LoadedPage
from fastfoto_linux.documents.modes import ColourMode


def peak_of(call) -> int:
    tracemalloc.start()
    try:
        call()
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


def test_an_over_cap_page_allocates_no_mask() -> None:
    pixels = np.full((8001, 10000), WHITE, dtype=np.uint8)  # 80.01 million pixels
    pixels[100:102, 100:102] = 0
    page = LoadedPage(pixels, ColourMode.BW, 600)
    seen: list[DespeckleStatus] = []
    plain = peak_of(lambda: render_page(page, ColourMode.BW))
    on = peak_of(lambda: render_page(page, ColourMode.BW, despeckle=True, on_despeckle=seen.append))
    assert seen == [DespeckleStatus.TOO_LARGE]
    assert on <= plain + 2**20


def test_a_low_resolution_page_allocates_no_mask() -> None:
    pixels = np.full((4000, 5000), WHITE, dtype=np.uint8)
    page = LoadedPage(pixels, ColourMode.BW, 100)
    seen: list[DespeckleStatus] = []
    plain = peak_of(lambda: render_page(page, ColourMode.BW))
    on = peak_of(lambda: render_page(page, ColourMode.BW, despeckle=True, on_despeckle=seen.append))
    assert seen == [DespeckleStatus.LOW_DPI]
    assert on <= plain + 2**20


@pytest.mark.parametrize("seed", range(5))
def test_the_pixels_are_the_old_formula_byte_for_byte(seed: int) -> None:
    rng = np.random.default_rng(seed)
    white = rng.random((int(rng.integers(1, 90)), int(rng.integers(1, 90)))) < 0.6
    old = np.where(white, WHITE, 0).astype(np.uint8)
    new = encode._white_to_pixels(white)
    assert new.dtype == np.uint8
    assert new.shape == white.shape
    assert np.array_equal(new, old)
    assert new.tobytes() == old.tobytes()


def test_the_pixels_of_a_large_mask_need_no_64_bit_temporary() -> None:
    white = np.ones((6000, 5000), dtype=bool)  # 30 million pixels
    peak = peak_of(lambda: encode._white_to_pixels(white))
    assert peak < 2 * white.size  # the old formula peaked at 8 bytes a pixel
