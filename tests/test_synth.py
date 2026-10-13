import cv2
import numpy as np
import pytest

from fastfoto_linux.pipeline.geometry import mm_to_px
from tests.synth import BACKGROUND_RGB, make_frame

DPI = 75


def _grey(frame: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)


def _photo_pixels(frame: np.ndarray, box) -> np.ndarray:
    return frame[box.y : box.y + box.h, box.x : box.x + box.w]


def test_frame_is_uint8_rgb_and_contains_the_expected_box() -> None:
    frame, box = make_frame(dpi=DPI)
    assert frame.dtype == np.uint8
    assert frame.ndim == 3
    assert frame.shape[2] == 3
    assert box.x >= 0
    assert box.y >= 0
    assert box.x + box.w <= frame.shape[1]
    assert box.y + box.h <= frame.shape[0]
    assert box.mm(DPI)[2:] == pytest.approx((178, 127), abs=0.5)
    assert box.mm(DPI)[:2] == pytest.approx((20, 0.5), abs=0.5)


def test_same_seed_is_deterministic_and_different_seed_differs() -> None:
    first, _ = make_frame(dpi=DPI, rng_seed=3, side="back", writing=True)
    again, _ = make_frame(dpi=DPI, rng_seed=3, side="back", writing=True)
    other, _ = make_frame(dpi=DPI, rng_seed=4, side="back", writing=True)
    assert np.array_equal(first, again)
    assert not np.array_equal(first, other)


def test_front_photo_is_dark_and_back_is_white_paper() -> None:
    front, front_box = make_frame(dpi=DPI, side="front")
    back, back_box = make_frame(dpi=DPI, side="back", imprint=False)
    assert np.median(_grey(_photo_pixels(front, front_box))) < 150
    assert np.median(_grey(_photo_pixels(back, back_box))) > 240


def test_background_is_blue_grey_with_noise() -> None:
    frame, box = make_frame(dpi=DPI)
    margin = frame[box.y : box.y + box.h, mm_to_px(4, DPI) : mm_to_px(15, DPI)]
    assert margin.reshape(-1, 3).mean(axis=0) == pytest.approx(BACKGROUND_RGB, abs=1.5)
    assert 1.0 < margin.reshape(-1, 3).std(axis=0).mean() < 6.0


def test_tail_is_pure_white_and_grey_band_precedes_it() -> None:
    frame, box = make_frame(dpi=DPI, tail_mm=40, white_strip=None)
    assert (frame[-1] == 255).all()
    assert (frame[-mm_to_px(40, DPI) :] == 255).all()
    band = frame[box.y + box.h + 2 : box.y + box.h + mm_to_px(8, DPI)]
    assert (_grey(band) < 230).all()


@pytest.mark.parametrize("strip", ["left", "right"])
def test_white_strip_sits_on_the_requested_edge_only(strip: str) -> None:
    frame, box = make_frame(dpi=DPI, white_strip=strip)
    rows = slice(box.y, box.y + box.h)
    left, right = _grey(frame[rows, 0:1]).mean(), _grey(frame[rows, -1:]).mean()
    bright, dim = (left, right) if strip == "left" else (right, left)
    assert bright >= 243
    assert dim < 230


def test_no_white_strip_when_disabled() -> None:
    frame, box = make_frame(dpi=DPI, white_strip=None)
    rows = slice(box.y, box.y + box.h)
    assert _grey(frame[rows, 0:1]).mean() < 230
    assert _grey(frame[rows, -1:]).mean() < 230


def test_imprint_adds_faint_dots_only_to_backs() -> None:
    plain, box = make_frame(dpi=150, side="back", imprint=False)
    marked, _ = make_frame(dpi=150, side="back", imprint=True)
    changed = _grey(_photo_pixels(marked, box)) < 215
    assert 0 < changed.sum() < 0.01 * changed.size
    assert (_grey(_photo_pixels(plain, box)) >= 215).all()
    front_off, _ = make_frame(dpi=DPI, side="front", imprint=False)
    front_on, _ = make_frame(dpi=DPI, side="front", imprint=True)
    assert np.array_equal(front_off, front_on)


def test_writing_adds_dark_strokes_to_backs_only() -> None:
    plain, box = make_frame(dpi=150, side="back", imprint=False)
    written, _ = make_frame(dpi=150, side="back", imprint=False, writing=True)
    dark = _grey(_photo_pixels(written, box)) < 150
    assert 0.001 * dark.size < dark.sum() < 0.1 * dark.size
    assert (_grey(_photo_pixels(plain, box)) >= 150).all()
    front_off, _ = make_frame(dpi=DPI, side="front")
    front_on, _ = make_frame(dpi=DPI, side="front", writing=True)
    assert np.array_equal(front_off, front_on)


def test_frame_grows_to_fit_large_photos_and_custom_margins() -> None:
    wide, box = make_frame(dpi=DPI, photo_mm=(250, 90), right_margin_mm=10)
    assert wide.shape[1] == box.x + box.w + mm_to_px(10, DPI)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"side": "side"},
        {"white_strip": "top"},
        {"photo_mm": (0, 100)},
        {"offset_mm": (-1, 0)},
    ],
)
def test_invalid_arguments_are_rejected(kwargs: dict) -> None:
    with pytest.raises(ValueError, match=r"side|white_strip|photo_mm"):
        make_frame(dpi=DPI, **kwargs)
