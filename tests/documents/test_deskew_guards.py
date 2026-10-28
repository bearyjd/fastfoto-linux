"""The estimate fails closed on odd pages, and its clipping and confidence checks see everything."""

import numpy as np
import pytest

from fastfoto_linux.documents import deskew_tables
from fastfoto_linux.documents.deskew import SkewStatus, estimate_skew
from fastfoto_linux.documents.loader import LoadedPage
from fastfoto_linux.documents.modes import ColourMode
from tests.documents.deskew_fixtures import (
    dashed_blocks,
    loaded,
    skewed,
    text_page,
    two_skews,
)


@pytest.mark.parametrize(("shape", "dpi"), [((20, 20), 2400), ((1, 5000), 300), ((5000, 1), 300)])
def test_a_tiny_or_extreme_page_is_not_an_error(shape, dpi: int) -> None:
    pixels = np.random.default_rng(0).integers(0, 256, shape, dtype=np.uint8)
    assert estimate_skew(loaded(pixels, dpi=dpi)).status is not SkewStatus.ESTIMATED


def _corner_mark(pixels: np.ndarray, value: int) -> np.ndarray:
    out = pixels.copy()
    out[:60, :60] = value
    return out


@pytest.mark.parametrize("value", [30, 150])
def test_a_mark_in_the_corner_that_the_turn_would_push_out_stops_it(value: int) -> None:
    pixels = _corner_mark(skewed(text_page(np.random.default_rng(3)), 80), value)
    assert estimate_skew(loaded(pixels)).status is SkewStatus.WOULD_CLIP


def test_a_mark_that_stays_inside_does_not_stop_it() -> None:
    mid = skewed(text_page(np.random.default_rng(3)), 80)
    mid[1000:1060, 800:860] = 150
    assert estimate_skew(loaded(mid)).status is SkewStatus.ESTIMATED


@pytest.mark.parametrize("stride_points", [300, 1000, 3000])
def test_the_clipping_check_sees_points_a_thinned_score_dropped(monkeypatch, stride_points) -> None:
    monkeypatch.setattr(deskew_tables, "MAX_POINTS", stride_points)
    pixels = skewed(text_page(np.random.default_rng(3)), 80)
    pixels[-9:, -9:] = 30  # three work pixels each way, last in the scan order
    assert estimate_skew(loaded(pixels)).status is SkewStatus.WOULD_CLIP


@pytest.mark.parametrize("dpi", [100, 150, 300])
def test_a_black_and_white_page_is_measured(dpi: int) -> None:
    grey = skewed(text_page(np.random.default_rng(3), dpi=dpi), 41)
    bw = np.where(grey < 128, 0, 255).astype(np.uint8)
    found = estimate_skew(LoadedPage(bw, ColourMode.BW, dpi))
    assert found.status is SkewStatus.ESTIMATED
    assert abs(found.tenths - -41) <= 1


@pytest.mark.parametrize("tilts", [(10, -33), (-17, 24), (100, -330), (60, 255)])
def test_a_second_tilt_between_the_samples_or_beyond_ten_degrees_makes_it_unsure(tilts) -> None:
    page = loaded(two_skews(0, tilts))
    assert estimate_skew(page).status in {SkewStatus.UNSURE, SkewStatus.EDGE}


def test_a_page_of_one_tilt_is_still_measured_with_the_wider_search() -> None:
    found = estimate_skew(loaded(skewed(text_page(np.random.default_rng(3)), -96)))
    assert found.status is SkewStatus.ESTIMATED


def test_a_one_pixel_stroke_in_the_corner_stops_the_turn_at_full_resolution() -> None:
    pixels = skewed(text_page(np.random.default_rng(3), dpi=600), 80)
    assert estimate_skew(loaded(pixels, dpi=600)).status is SkewStatus.ESTIMATED
    pixels[:240, :1] = 0  # averaged over a work pixel it is grey 200
    assert estimate_skew(loaded(pixels, dpi=600)).status is SkewStatus.WOULD_CLIP


def test_a_one_pixel_hairline_on_the_bottom_edge_stops_the_turn() -> None:
    pixels = skewed(text_page(np.random.default_rng(3), dpi=600), 80)
    pixels[-1:, :300] = 0  # in the rows the work grid's blocks leave over
    assert estimate_skew(loaded(pixels, dpi=600)).status is SkewStatus.WOULD_CLIP


@pytest.mark.parametrize("rival", [-252, 247, 237])
def test_a_second_tilt_between_the_half_degree_samples_makes_it_unsure(rival: int) -> None:
    assert estimate_skew(loaded(dashed_blocks((40, rival)))).status in {
        SkewStatus.UNSURE,
        SkewStatus.EDGE,
    }


DIGIT = (24, 30)  # a small digit's ink box: width, height in pixels at 600 dpi
FRAME_EDGE_DIGITS = {  # (left, top): wholly inside the 3543 x 4724 frame, near its edge
    "footer": (1392, 4673),
    "header": (3543 - 1392 - DIGIT[0], 4724 - 4673 - DIGIT[1]),
    "right edge": (3543 - 43, 3000),
    "left edge": (43 - DIGIT[0], 4724 - 3000 - DIGIT[1]),
}


@pytest.mark.parametrize("where", list(FRAME_EDGE_DIGITS))
def test_a_small_mark_the_turn_would_cut_part_of_stops_it(where: str) -> None:
    pixels = skewed(text_page(np.random.default_rng(3), dpi=600), 80)
    left, top = FRAME_EDGE_DIGITS[where]
    assert estimate_skew(loaded(pixels, dpi=600)).status is SkewStatus.ESTIMATED
    pixels[top : top + DIGIT[1], left : left + DIGIT[0]] = 20
    assert estimate_skew(loaded(pixels, dpi=600)).status is SkewStatus.WOULD_CLIP


@pytest.mark.parametrize("tilt", [80, -80, 96])
def test_text_with_ordinary_margins_is_still_measured(tilt: int) -> None:
    page = text_page(np.random.default_rng(4), margin_mm=15)
    assert estimate_skew(loaded(skewed(page, tilt))).status is SkewStatus.ESTIMATED
