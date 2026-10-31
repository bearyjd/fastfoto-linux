"""Downscaling for the small preset: never up, never in place, one scale for both sides."""

import numpy as np
import pytest

from fastfoto_linux.output.resample import downscale, downscale_to_dpi


def picture(height: int, width: int) -> np.ndarray:
    rng = np.random.default_rng(7)
    return rng.integers(0, 256, size=(height, width, 3), dtype=np.uint8)


def test_within_the_limit_returns_the_same_object() -> None:
    pixels = picture(40, 60)

    result, scale = downscale(pixels, 100)

    assert result is pixels
    assert scale == 1.0


def test_a_long_edge_exactly_at_the_limit_is_not_resampled() -> None:
    pixels = picture(40, 60)

    result, scale = downscale(pixels, 60)

    assert result is pixels
    assert scale == 1.0


@pytest.mark.parametrize("shape", [(40, 200), (200, 40)])
def test_wide_and_tall_inputs_cap_their_long_edge(shape: tuple[int, int]) -> None:
    pixels = picture(*shape)

    result, scale = downscale(pixels, 100)

    assert max(result.shape[:2]) == 100
    assert scale == pytest.approx(0.5)
    assert abs(result.shape[0] / result.shape[1] - shape[0] / shape[1]) < 0.05


def test_the_input_is_not_modified_and_never_enlarged() -> None:
    pixels = picture(80, 120)
    before = pixels.copy()

    result, _ = downscale(pixels, 60)

    assert np.array_equal(pixels, before)
    assert result is not pixels
    assert result.shape[0] <= 80 and result.shape[1] <= 120


def test_a_thin_image_keeps_at_least_one_pixel() -> None:
    result, _ = downscale(picture(1, 1000), 10)

    assert result.shape[:2] == (1, 10)


def test_grey_arrays_work() -> None:
    result, _ = downscale(np.zeros((60, 120), dtype=np.uint8), 60)

    assert result.shape == (30, 60)


def test_dpi_600_to_200_gives_a_third_of_the_pixels() -> None:
    pixels = picture(300, 240)

    result, dpi = downscale_to_dpi(pixels, 600, 200)

    assert dpi == 200
    assert result.shape[:2] == (100, 80)


def test_dpi_within_the_limit_is_unchanged() -> None:
    pixels = picture(30, 24)

    result, dpi = downscale_to_dpi(pixels, 150, 200)

    assert result is pixels
    assert dpi == 150


@pytest.mark.parametrize("call", [lambda p: downscale(p, 0), lambda p: downscale_to_dpi(p, 600, 0)])
def test_a_limit_below_one_is_refused(call) -> None:
    with pytest.raises(ValueError):
        call(picture(10, 10))
