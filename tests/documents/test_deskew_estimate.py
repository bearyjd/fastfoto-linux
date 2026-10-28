"""The skew estimate recovers a synthetic tilt (sign pinned by an independent rotation)."""

import numpy as np
import pytest

from fastfoto_linux.documents import deskew_tables
from fastfoto_linux.documents.deskew import SkewStatus, estimate_skew
from fastfoto_linux.documents.deskew_warp import deskewed
from fastfoto_linux.documents.modes import ColourMode
from tests.documents.deskew_fixtures import (
    few_lines,
    hard_page,
    loaded,
    rgb,
    skewed,
    text_page,
)

ANGLES = [5, -5, 13, -13, 27, -27, 41, -41, 75, -75, 96, -96]


def _undo(pixels: np.ndarray, tenths: int):
    return loaded(deskewed(pixels, tenths, ColourMode.GREY))


@pytest.mark.parametrize("tilt", ANGLES)
def test_a_tilted_text_page_is_measured_and_straightened(tilt: int) -> None:
    pixels = skewed(text_page(np.random.default_rng(tilt + 200)), tilt)
    found = estimate_skew(loaded(pixels))
    assert found.status is SkewStatus.ESTIMATED
    assert abs(found.tenths - -tilt) <= 1  # turned clockwise by tilt, so straightened by -tilt
    assert estimate_skew(_undo(pixels, found.tenths)).status is SkewStatus.LEVEL


@pytest.mark.parametrize("seed", [1, 2, 3])
@pytest.mark.parametrize("tilt", [5, -27, 41, -96])
def test_a_hard_page_is_measured_within_a_tenth(seed: int, tilt: int) -> None:
    pixels = skewed(hard_page(seed), tilt)
    found = estimate_skew(loaded(pixels))
    assert found.status is SkewStatus.ESTIMATED
    assert abs(found.tenths - -tilt) <= 1
    assert estimate_skew(_undo(pixels, found.tenths)).status is SkewStatus.LEVEL


def test_a_colour_page_gives_the_estimate_of_its_grey() -> None:
    pixels = skewed(text_page(np.random.default_rng(7)), 41)
    assert estimate_skew(rgb(pixels)) == estimate_skew(loaded(pixels))


def test_two_calls_agree() -> None:
    page = loaded(skewed(hard_page(2), -27))
    assert estimate_skew(page) == estimate_skew(page)


def test_a_subsampled_huge_ink_case_is_stable(monkeypatch: pytest.MonkeyPatch) -> None:
    page = loaded(skewed(text_page(np.random.default_rng(4)), 27))
    monkeypatch.setattr(deskew_tables, "MAX_POINTS", 5000)
    first = estimate_skew(page)
    assert first == estimate_skew(page)
    assert first.status is SkewStatus.ESTIMATED
    assert abs(first.tenths - -27) <= 2


def test_two_lines_either_abstain_or_are_right() -> None:
    found = estimate_skew(loaded(skewed(few_lines(), 41)))
    assert found.status is not SkewStatus.ESTIMATED or abs(found.tenths - -41) <= 2
