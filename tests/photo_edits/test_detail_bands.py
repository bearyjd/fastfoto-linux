"""Banded processing: exactness against the whole image, sigma rule, cancel and read-only."""

from pathlib import Path
from threading import Event

import numpy as np
import pytest

from fastfoto_linux.photo_edits import (
    PhotoDetail,
    PhotoEditCancelledError,
    PhotoEditError,
    PhotoEditRecipe,
    detail,
    render,
    update_detail,
)
from tests.photo_edits.detail_helpers import (
    NlmSpy,
    noisy_pixels,
    noisy_source,
    reference_window,
    with_pixels,
)
from tests.photo_edits.helpers import eye
from tests.photo_edits.straighten_helpers import noise


@pytest.fixture
def tiny_bands(monkeypatch):
    monkeypatch.setattr(detail, "DETAIL_BAND_PIXELS", 1)


def _image() -> np.ndarray:
    return noisy_pixels(131, 96, seed=5, sigma=20.0)


def test_denoise_bands_equal_the_whole_image_kernel(tiny_bands, monkeypatch) -> None:
    control = PhotoDetail(100, 100, 0)
    whole = detail._denoise_kernel(control)(_image())
    spy = NlmSpy()
    monkeypatch.setattr(detail, "cv2", spy)
    banded = _image()
    detail.apply_denoise(banded, control, Event())
    assert len(spy.calls) > 3 * 2
    assert np.array_equal(banded, whole)


@pytest.mark.parametrize("dpi", [300.0, 600.0, 1200.0])
def test_sharpen_bands_equal_the_whole_image_kernel(tiny_bands, dpi: float) -> None:
    control = PhotoDetail(0, 0, 100)
    whole = detail._sharpen_kernel(control, dpi)(_image())
    banded = _image()
    detail.apply_sharpen(banded, control, dpi, Event())
    assert np.array_equal(banded, whole)


def test_the_band_size_follows_the_halo_and_the_pixel_budget(monkeypatch) -> None:
    spy = NlmSpy()
    monkeypatch.setattr(detail, "cv2", spy)
    monkeypatch.setattr(detail, "DETAIL_BAND_PIXELS", 1)
    detail.apply_denoise(_image(), PhotoDetail(50, 0, 0), Event())
    # 131 rows in bands of max(4 * halo, 1 // width) = 40 rows: 4 bands.
    assert len(spy.calls) == 4
    spy.calls.clear()
    monkeypatch.setattr(detail, "DETAIL_BAND_PIXELS", 10**9)
    monkeypatch.setattr(detail, "MAX_BAND_PIXELS", 10**12)
    detail.apply_denoise(_image(), PhotoDetail(50, 0, 0), Event())
    assert len(spy.calls) == 1


@pytest.mark.parametrize(
    ("dpi", "sigma", "ksize"), [(150, 0.5, 5), (300, 1.0, 7), (600, 2.0, 13), (1200, 3.0, 19)]
)
def test_sigma_and_kernel_size_follow_the_dpi(dpi: float, sigma: float, ksize: int) -> None:
    assert detail.sharpen_window(dpi) == (sigma, ksize)
    assert reference_window(dpi) == (sigma, ksize)


def test_the_window_matches_the_reference_over_a_dpi_range() -> None:
    for dpi in (1, 50, 99, 150, 250, 300, 450, 599, 600, 900, 1200, 4800, 1e9):
        assert detail.sharpen_window(dpi) == reference_window(dpi)


def test_a_cancel_after_the_first_band_stops_the_next(tiny_bands, monkeypatch) -> None:
    cancel = Event()
    spy = NlmSpy(on_call=lambda n: cancel.set() if n == 1 else None)
    monkeypatch.setattr(detail, "cv2", spy)
    with pytest.raises(PhotoEditCancelledError):
        detail.apply_denoise(_image(), PhotoDetail(70, 0, 0), cancel)
    assert len(spy.calls) == 1


def test_a_cancelled_render_leaves_the_source_and_masks_untouched(
    tmp_path: Path, tiny_bands, monkeypatch
) -> None:
    source = with_pixels(tmp_path, noise(131, 64, seed=7))
    before, mask = source.pixels.copy(), eye().mask.copy()
    recipe = update_detail(PhotoEditRecipe(source, (eye(),)), PhotoDetail(50, 0, 50))
    cancel = Event()
    spy = NlmSpy(on_call=lambda n: cancel.set())
    monkeypatch.setattr(detail, "cv2", spy)
    with pytest.raises(PhotoEditCancelledError):
        render(source, recipe, cancel=cancel)
    assert len(spy.calls) == 1
    assert np.array_equal(source.pixels, before)
    assert np.array_equal(recipe.eyes[0].mask, mask)


def test_an_already_cancelled_event_stops_before_the_first_band() -> None:
    cancel = Event()
    cancel.set()
    pixels = _image()
    original = pixels.copy()
    with pytest.raises(PhotoEditCancelledError):
        detail.apply_sharpen(pixels, PhotoDetail(0, 0, 50), 300.0, cancel)
    assert np.array_equal(pixels, original)


def test_a_non_contiguous_buffer_is_rejected() -> None:
    wide = np.zeros((16, 16, 3), dtype=np.uint8)[:, ::2]
    with pytest.raises(PhotoEditError, match="contiguous"):
        detail.apply_denoise(wide, PhotoDetail(50, 50, 0), Event())
    with pytest.raises(PhotoEditError, match="contiguous"):
        detail.apply_sharpen(wide, PhotoDetail(0, 0, 50), 300.0, Event())


def test_a_neutral_stage_returns_without_looking_at_the_buffer() -> None:
    wide = np.zeros((16, 16, 3), dtype=np.uint8)[:, ::2]
    detail.apply_denoise(wide, PhotoDetail(0, 0, 100), Event())
    detail.apply_sharpen(wide, PhotoDetail(100, 100, 0), 300.0, Event())


def test_a_short_image_is_a_single_band(tmp_path: Path) -> None:
    source = noisy_source(tmp_path, height=5, width=7)
    recipe = update_detail(PhotoEditRecipe(source), PhotoDetail(50, 50, 50))
    assert render(source, recipe, cancel=Event()).shape == (5, 7, 3)


def test_a_very_wide_image_is_refused_with_a_fixed_message() -> None:
    wide = np.zeros((1, 140_000, 3), dtype=np.uint8)
    with pytest.raises(PhotoEditError, match=r"^image too wide for detail adjustments$"):
        detail.apply_denoise(wide, PhotoDetail(50, 0, 0), Event())
    wider = np.zeros((1, 500_000, 3), dtype=np.uint8)
    with pytest.raises(PhotoEditError, match=r"^image too wide for detail adjustments$"):
        detail.apply_sharpen(wider, PhotoDetail(0, 0, 50), 300.0, Event())


def test_the_band_cap_leaves_every_realistic_scan_alone() -> None:
    halo = detail.DENOISE_HALO
    for width in (1800, 3600, 6000, 100_000):
        rows = max(4 * halo, detail.DETAIL_BAND_PIXELS // width)
        assert (rows + 2 * halo) * width <= detail.MAX_BAND_PIXELS


@pytest.mark.parametrize(
    "bad",
    [
        np.zeros((8, 8, 3), dtype=np.float32),
        np.zeros((8, 8), dtype=np.uint8),
        np.zeros((8, 8, 4), dtype=np.uint8),
        np.zeros((0, 8, 3), dtype=np.uint8),
    ],
)
def test_only_uint8_rgb_buffers_are_accepted(bad: np.ndarray) -> None:
    with pytest.raises(PhotoEditError, match="uint8 RGB"):
        detail.apply_denoise(bad, PhotoDetail(50, 50, 0), Event())
    with pytest.raises(PhotoEditError, match="uint8 RGB"):
        detail.apply_sharpen(bad, PhotoDetail(0, 0, 50), 300.0, Event())
