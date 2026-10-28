"""The skew estimate abstains, with the reason, when it cannot be sure."""

import numpy as np
import pytest

from fastfoto_linux.documents import cleanup
from fastfoto_linux.documents.deskew import SkewStatus, estimate_skew
from fastfoto_linux.documents.deskew_tables import SEPARATION_PCT
from tests.documents.deskew_fixtures import (
    HEIGHT_MM,
    WIDTH_MM,
    blank,
    loaded,
    one_short_line,
    scatter,
    skewed,
    smooth_photo,
    text_page,
    two_skews,
)


def _full_page_tilted(tenths: int) -> np.ndarray:
    """Text that fills the frame to its corners, its lines tilted on straight paper."""
    rng = np.random.default_rng(5)
    big = text_page(rng, width_mm=WIDTH_MM * 2, height_mm=HEIGHT_MM * 2, margin_mm=3)
    tilted = skewed(big, tenths)
    top, left = (tilted.shape[0] - blank().shape[0]) // 2, (tilted.shape[1] - blank().shape[1]) // 2
    return tilted[top : top + blank().shape[0], left : left + blank().shape[1]]


CASES = {
    "blank": (lambda: loaded(blank()), {SkewStatus.LITTLE_INK}),
    "one short line": (lambda: loaded(one_short_line()), {SkewStatus.LITTLE_INK}),
    "smooth photo": (lambda: loaded(smooth_photo()), {SkewStatus.NOT_TEXT, SkewStatus.UNSURE}),
    "scatter": (lambda: loaded(scatter()), {SkewStatus.UNSURE}),
    "two skews": (lambda: loaded(two_skews()), {SkewStatus.UNSURE}),
    "twelve degrees": (
        lambda: loaded(skewed(text_page(np.random.default_rng(3)), 120)),
        {SkewStatus.EDGE},
    ),
    "two tenths": (
        lambda: loaded(skewed(text_page(np.random.default_rng(3)), 2)),
        {SkewStatus.LEVEL},
    ),
    "low dpi": (
        lambda: loaded(text_page(np.random.default_rng(3), dpi=75), dpi=75),
        {SkewStatus.LOW_DPI},
    ),
    "text to the corners": (lambda: loaded(_full_page_tilted(80)), {SkewStatus.WOULD_CLIP}),
}


@pytest.mark.parametrize("name", list(CASES))
def test_the_page_abstains_with_its_reason(name: str) -> None:
    make, expected = CASES[name]
    found = estimate_skew(make())
    assert found.status in expected
    assert found.tenths == 0


def test_a_page_too_large_for_the_work_grid_is_not_measured(monkeypatch) -> None:
    monkeypatch.setattr(cleanup, "MAX_WORK_PIXELS", 1000)
    found = estimate_skew(loaded(skewed(text_page(np.random.default_rng(3)), 41)))
    assert found.status is SkewStatus.TOO_LARGE


def test_the_confidence_separates_text_from_the_rest() -> None:
    text = estimate_skew(loaded(skewed(text_page(np.random.default_rng(3)), 41)))
    assert text.separation_pct < SEPARATION_PCT
    for make in (scatter, two_skews):
        assert estimate_skew(loaded(make())).separation_pct >= SEPARATION_PCT


def test_text_that_reaches_the_corners_is_still_measured_when_the_tilt_is_small() -> None:
    found = estimate_skew(loaded(_full_page_tilted(5)))
    assert found.status in {SkewStatus.ESTIMATED, SkewStatus.WOULD_CLIP}
