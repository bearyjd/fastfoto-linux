"""Document pages under each export preset: JPEG settings, resolution caps, PNG, untouched B/W."""

import io

import numpy as np
import pytest
from PIL import Image, JpegImagePlugin

from fastfoto_linux.documents.encode import encode_page
from fastfoto_linux.documents.loader import LoadedPage
from fastfoto_linux.documents.modes import ColourMode
from fastfoto_linux.output.presets import ExportPreset

C, G, B = ColourMode.COLOUR, ColourMode.GREY, ColourMode.BW
ALL = [None, *ExportPreset]


def grey_pixels(height: int = 240, width: int = 300) -> np.ndarray:
    rng = np.random.default_rng(5)
    ramp = np.linspace(0, 200, width, dtype=np.float32)[None, :]
    return np.clip(ramp + rng.integers(0, 55, size=(height, width)), 0, 255).astype(np.uint8)


def grey(dpi: int, **shape: int) -> LoadedPage:
    return LoadedPage(grey_pixels(**shape), G, dpi)


def colour(dpi: int) -> LoadedPage:
    pixels = np.stack([grey_pixels(), grey_pixels()[::-1], grey_pixels()[:, ::-1]], axis=2)
    return LoadedPage(pixels, C, dpi)


def decode(data: bytes) -> Image.Image:
    picture = Image.open(io.BytesIO(data))
    picture.load()
    return picture


def test_none_bytes_equal_the_legacy_jpeg_call() -> None:
    page = colour(100)
    buffer = io.BytesIO()
    Image.fromarray(page.pixels).save(buffer, "JPEG", quality=85, dpi=(100, 100))

    encoded = encode_page(page, C, preset=None)

    assert encoded.data == buffer.getvalue()
    assert encoded.preset is None


def test_the_preset_is_recorded_on_the_page() -> None:
    assert encode_page(colour(100), C, preset=ExportPreset.SMALL).preset is ExportPreset.SMALL


def test_high_quality_is_444_and_bigger_than_the_default() -> None:
    page = colour(100)

    high = encode_page(page, C, preset=ExportPreset.HIGH_QUALITY)
    plain = encode_page(page, C)

    assert JpegImagePlugin.get_sampling(decode(high.data)) == 0
    assert JpegImagePlugin.get_sampling(decode(plain.data)) == 2
    assert len(high.data) > len(plain.data)


def test_small_caps_a_600_dpi_page_at_200_dpi() -> None:
    page = grey(600)

    small = encode_page(page, G, preset=ExportPreset.SMALL)

    assert small.dpi == 200
    assert (small.width, small.height) == (100, 80)
    picture = decode(small.data)
    assert picture.size == (100, 80)
    assert round(picture.info["dpi"][0]) == 200
    assert len(small.data) < len(encode_page(page, G).data)


def test_small_leaves_a_150_dpi_page_alone() -> None:
    page = grey(150)

    small = encode_page(page, G, preset=ExportPreset.SMALL)

    assert (small.dpi, small.width, small.height) == (150, 300, 240)
    assert decode(small.data).size == (300, 240)


@pytest.mark.parametrize("page", [grey(300), colour(300)], ids=["grey", "colour"])
def test_lossless_is_a_png_with_exact_pixels(page: LoadedPage) -> None:
    encoded = encode_page(page, page.kind, preset=ExportPreset.LOSSLESS)

    picture = decode(encoded.data)
    assert picture.format == "PNG"
    assert np.array_equal(np.asarray(picture), page.pixels)
    assert round(picture.info["dpi"][0]) == 300


@pytest.mark.parametrize("preset", ALL, ids=str)
def test_black_and_white_is_group4_at_native_size_under_every_preset(
    preset: ExportPreset | None,
) -> None:
    pixels = np.where(grey_pixels(240, 600) > 100, 255, 0).astype(np.uint8)
    page = LoadedPage(pixels, B, 600)

    encoded = encode_page(page, B, preset=preset)

    picture = decode(encoded.data)
    assert picture.format == "TIFF"
    assert picture.info["compression"] == "group4"
    assert picture.size == (600, 240)
    assert (encoded.dpi, encoded.width, encoded.height) == (600, 600, 240)
