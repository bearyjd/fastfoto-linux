"""A page too large to clean within the memory bound is left as it is, and says so."""

import numpy as np
import pytest

from fastfoto_linux.documents import cleanup
from fastfoto_linux.documents.encode import render_page
from fastfoto_linux.documents.loader import LoadedPage
from fastfoto_linux.documents.modes import CleanupPolicy, ColourMode

LIMIT = 100 * 100


def paper(height: int, width: int, *, colour: bool = False) -> np.ndarray:
    shape = (height, width, 3) if colour else (height, width)
    pixels = np.full(shape, 235, np.uint8)
    pixels[::9, ::7] = 30
    return pixels


def test_the_limit_is_documented_in_work_pixels() -> None:
    # About 42 bytes per work pixel at the peak: 12 million is about half a gibibyte.
    assert cleanup.MAX_WORK_PIXELS == 12_000_000


@pytest.mark.parametrize("colour", [False, True])
def test_just_below_and_at_the_limit_is_cleaned(monkeypatch, colour: bool) -> None:
    monkeypatch.setattr(cleanup, "MAX_WORK_PIXELS", LIMIT)
    output = ColourMode.COLOUR if colour else ColourMode.GREY
    for width in (LIMIT // 100 - 1, LIMIT // 100):
        src = paper(100, width, colour=colour)
        result = cleanup.clean_pixels(src, 150, output, CleanupPolicy.STRONG)
        assert result.status is cleanup.CleanupStatus.APPLIED


@pytest.mark.parametrize("colour", [False, True])
def test_just_above_the_limit_is_too_large_and_unchanged(monkeypatch, colour: bool) -> None:
    monkeypatch.setattr(cleanup, "MAX_WORK_PIXELS", LIMIT)
    output = ColourMode.COLOUR if colour else ColourMode.GREY
    src = paper(100, 101, colour=colour)
    before = src.copy()
    result = cleanup.clean_pixels(src, 150, output, CleanupPolicy.STRONG)
    assert result.status is cleanup.CleanupStatus.TOO_LARGE and result.pixels is None
    assert np.array_equal(src, before)
    page = LoadedPage(src, ColourMode.COLOUR if colour else ColourMode.GREY, 150)
    plain = render_page(page, output, CleanupPolicy.OFF)
    assert np.array_equal(render_page(page, output, CleanupPolicy.STRONG), plain)


def test_the_limit_counts_the_work_grid_not_the_page(monkeypatch) -> None:
    monkeypatch.setattr(cleanup, "MAX_WORK_PIXELS", LIMIT)
    # 300 dpi works at half the resolution: 200 x 200 pixels are a 100 x 100 grid.
    fits = cleanup.clean_pixels(paper(200, 200), 300, ColourMode.GREY, CleanupPolicy.LIGHT)
    assert fits.status is cleanup.CleanupStatus.APPLIED
    over = cleanup.clean_pixels(paper(200, 202), 300, ColourMode.GREY, CleanupPolicy.LIGHT)
    assert over.status is cleanup.CleanupStatus.TOO_LARGE


def test_the_real_limit_stops_a_huge_page_before_any_work() -> None:
    thin = np.full((1, cleanup.MAX_WORK_PIXELS + 1), 235, np.uint8)
    result = cleanup.clean_pixels(thin, 150, ColourMode.GREY, CleanupPolicy.LIGHT)
    assert result.status is cleanup.CleanupStatus.TOO_LARGE and result.pixels is None


def test_off_and_black_and_white_win_over_too_large(monkeypatch) -> None:
    monkeypatch.setattr(cleanup, "MAX_WORK_PIXELS", LIMIT)
    src = paper(100, 101)
    assert (
        cleanup.clean_pixels(src, 150, ColourMode.GREY, CleanupPolicy.OFF).status
        is cleanup.CleanupStatus.OFF
    )
    assert (
        cleanup.clean_pixels(src, 150, ColourMode.BW, CleanupPolicy.LIGHT).status
        is cleanup.CleanupStatus.BW
    )


def test_the_answer_is_deterministic(monkeypatch) -> None:
    monkeypatch.setattr(cleanup, "MAX_WORK_PIXELS", LIMIT)
    src = paper(100, 101)
    first = cleanup.clean_pixels(src, 150, ColourMode.GREY, CleanupPolicy.LIGHT)
    second = cleanup.clean_pixels(src, 150, ColourMode.GREY, CleanupPolicy.LIGHT)
    assert first == second
