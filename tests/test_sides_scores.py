"""paper_score and handwriting detection on synthetic fronts and backs."""

import cv2
import numpy as np
import pytest

from fastfoto_linux.pipeline.geometry import mm_to_px
from fastfoto_linux.pipeline.sides import (
    HANDWRITING_MIN_CANDIDATES,
    handwriting_candidates,
    has_handwriting,
    paper_score,
)
from tests.sides_helpers import cropped_back, region
from tests.synth import make_frame

SMALL_BACK_MM = (120, 80)


def _front(dpi: int, **kwargs) -> np.ndarray:
    frame, box = make_frame(dpi=dpi, side="front", **kwargs)
    return region(frame, box)


def _solid(rgb: tuple[int, int, int], size: int = 64) -> np.ndarray:
    return np.full((size, size, 3), rgb, dtype=np.uint8)


# --- paper_score ---------------------------------------------------------------------------


def test_pure_white_scores_one_and_black_scores_zero() -> None:
    assert paper_score(_solid((255, 255, 255))) == pytest.approx(1.0)
    assert paper_score(_solid((0, 0, 0))) == 0.0


def test_bright_but_saturated_colour_is_not_paper() -> None:
    assert paper_score(_solid((250, 255, 150))) == 0.0


def test_grey_just_below_the_paper_level_is_not_paper() -> None:
    assert paper_score(_solid((229, 229, 229))) == 0.0
    assert paper_score(_solid((231, 231, 231))) == pytest.approx(1.0)


def test_score_is_the_paper_fraction() -> None:
    img = _solid((255, 255, 255), size=100)
    img[:, :30] = 0
    assert paper_score(img) == pytest.approx(0.7, abs=0.03)


@pytest.mark.parametrize("dpi", [150, 300])
def test_synthetic_back_scores_high_and_front_scores_low(dpi: int) -> None:
    assert paper_score(cropped_back(dpi)) > 0.9
    assert paper_score(cropped_back(dpi, writing=True)) > 0.85
    assert paper_score(_front(dpi)) < 0.05


def test_paper_score_does_not_modify_its_input() -> None:
    img = cropped_back(150, writing=True)
    before = img.copy()
    paper_score(img)
    assert np.array_equal(img, before)


@pytest.mark.parametrize(
    "bad",
    [np.zeros((10, 10), dtype=np.uint8), np.zeros((10, 10, 3), dtype=np.float32)],
)
def test_paper_score_rejects_malformed_images(bad: np.ndarray) -> None:
    with pytest.raises(ValueError, match="RGB"):
        paper_score(bad)


# --- handwriting ---------------------------------------------------------------------------


@pytest.mark.parametrize("dpi", [150, 300])
@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_handwritten_back_has_far_more_candidates_than_the_threshold(dpi: int, seed: int) -> None:
    back = cropped_back(dpi, writing=True, rng_seed=seed)
    assert handwriting_candidates(back, dpi) >= HANDWRITING_MIN_CANDIDATES + 5
    assert has_handwriting(back, dpi)


@pytest.mark.parametrize("dpi", [150, 300])
@pytest.mark.parametrize("seed", [0, 1, 2])
def test_imprint_only_back_has_no_candidates(dpi: int, seed: int) -> None:
    back = cropped_back(dpi, imprint=True, rng_seed=seed)
    assert handwriting_candidates(back, dpi) <= 1
    assert not has_handwriting(back, dpi)


def test_blank_back_has_no_writing() -> None:
    back = cropped_back(150, imprint=False)
    assert handwriting_candidates(back, 150) == 0
    assert not has_handwriting(back, 150)


def test_imprint_beside_handwriting_does_not_add_candidates() -> None:
    plain = cropped_back(300, writing=True, imprint=False, rng_seed=5)
    marked = cropped_back(300, writing=True, imprint=True, rng_seed=5)
    assert handwriting_candidates(marked, 300) == handwriting_candidates(plain, 300)


@pytest.mark.parametrize("dpi", [150, 300, 450, 600])
def test_classification_is_stable_across_resolutions(dpi: int) -> None:
    written = cropped_back(dpi, writing=True, imprint=True, photo_mm=SMALL_BACK_MM)
    imprint = cropped_back(dpi, imprint=True, photo_mm=SMALL_BACK_MM)
    assert has_handwriting(written, dpi)
    assert not has_handwriting(imprint, dpi)


def test_candidate_counts_agree_between_300_and_600_dpi() -> None:
    low = cropped_back(300, writing=True, photo_mm=SMALL_BACK_MM, rng_seed=2)
    high = cv2.resize(low, None, fx=2, fy=2, interpolation=cv2.INTER_LINEAR)
    assert abs(handwriting_candidates(high, 600) - handwriting_candidates(low, 300)) <= 2


def _with_dark(back: np.ndarray, dpi: int, rows: slice, cols: slice) -> np.ndarray:
    out = back.copy()
    out[rows, cols] = 60
    return out


def test_long_dark_bars_are_lines_not_writing() -> None:
    dpi = 150
    back = cropped_back(dpi, imprint=False)
    top = mm_to_px(30, dpi)
    bar = slice(top, top + mm_to_px(2.5, dpi))
    marked = _with_dark(back, dpi, bar, slice(mm_to_px(20, dpi), mm_to_px(110, dpi)))
    assert handwriting_candidates(marked, dpi) == 0


def _with_ring(back: np.ndarray, dpi: int, gap_mm: float) -> np.ndarray:
    """Draw a 2 mm dark frame ``gap_mm`` in from the edge."""
    out = back.copy()
    gap, width = mm_to_px(gap_mm, dpi), mm_to_px(2.0, dpi)
    height, wide = out.shape[:2]
    out[gap : height - gap, gap : wide - gap] = 60
    inner = (slice(gap + width, height - gap - width), slice(gap + width, wide - gap - width))
    out[inner] = back[inner]
    return out


@pytest.mark.parametrize("gap_mm", [1.0, 6.0])
def test_a_dark_border_ring_is_not_writing_inside_or_outside_the_inset(gap_mm: float) -> None:
    back = cropped_back(150, imprint=False)
    assert handwriting_candidates(_with_ring(back, 150, gap_mm), 150) == 0


def test_tiny_or_huge_blobs_are_not_candidates() -> None:
    dpi = 150
    back = cropped_back(dpi, imprint=False)
    speck = _with_dark(back, dpi, slice(100, 103), slice(100, 103))  # a 0.5 mm speck
    block = _with_dark(back, dpi, slice(100, 100 + mm_to_px(40, dpi)), slice(100, 100 + 30))
    assert handwriting_candidates(speck, dpi) == 0
    assert handwriting_candidates(block, dpi) == 0  # 40 mm tall: a stain, not a letter


def test_image_smaller_than_the_inset_has_no_candidates() -> None:
    tiny = np.zeros((20, 20, 3), dtype=np.uint8)
    assert handwriting_candidates(tiny, 150) == 0
    assert not has_handwriting(tiny, 150)


def test_handwriting_does_not_modify_its_input() -> None:
    back = cropped_back(600, writing=True, photo_mm=SMALL_BACK_MM)
    before = back.copy()
    handwriting_candidates(back, 600)
    assert np.array_equal(back, before)


def test_handwriting_rejects_bad_input() -> None:
    with pytest.raises(ValueError, match="RGB"):
        handwriting_candidates(np.zeros((50, 50), dtype=np.uint8), 150)
    with pytest.raises(ValueError, match="dpi"):
        handwriting_candidates(cropped_back(150), 0)
