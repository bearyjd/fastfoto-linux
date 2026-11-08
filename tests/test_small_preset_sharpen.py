"""The small preset sharpens after its own downscale; every other path is left alone."""

import io
from threading import Event

import numpy as np
import pytest
from PIL import Image

from fastfoto_linux.output import photo_encode
from fastfoto_linux.output.photo_encode import encode_photo
from fastfoto_linux.output.presets import PHOTO_EXPORTS, ExportPreset
from fastfoto_linux.output.resample import downscale
from fastfoto_linux.photo_edits.detail import apply_sharpen
from fastfoto_linux.photo_edits.model import PhotoDetail

EXIF = b""
XMP = b"<x/>"


def picture(height: int, width: int) -> np.ndarray:
    rng = np.random.default_rng(7)
    base = rng.integers(0, 256, (height // 8 + 1, width // 8 + 1, 3), dtype=np.uint8)
    big = np.kron(base, np.ones((8, 8, 1), dtype=np.uint8))
    return np.ascontiguousarray(big[:height, :width])


def encode(array: np.ndarray, preset: ExportPreset | None, dpi: int = 600) -> bytes:
    return encode_photo(array, dpi=dpi, quality=95, preset=preset, exif=EXIF, xmp=XMP)


def small_jpeg(array: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(array).save(buffer, "JPEG", quality=80, subsampling=2, dpi=(1, 1))
    return buffer.getvalue()


def pixels(data: bytes) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(data)).convert("RGB")).astype(int)


def test_only_small_has_a_sharpen_amount() -> None:
    amounts = {preset: PHOTO_EXPORTS[preset].sharpen for preset in ExportPreset}
    assert amounts[ExportPreset.SMALL] > 0
    assert amounts[ExportPreset.HIGH_QUALITY] == 0
    assert amounts[ExportPreset.LOSSLESS] == 0


def test_small_sharpens_after_the_downscale_with_the_scaled_dpi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[tuple[int, ...], int, float]] = []

    def spy(array: np.ndarray, detail: PhotoDetail, dpi: float, cancel: Event) -> None:
        calls.append((array.shape, detail.sharpen, dpi))

    monkeypatch.setattr(photo_encode, "apply_sharpen", spy)
    encode(picture(3000, 4000), ExportPreset.SMALL, dpi=600)

    sharpen = PHOTO_EXPORTS[ExportPreset.SMALL].sharpen
    assert calls == [((1536, 2048, 3), sharpen, 600 * 2048 / 4000)]


def test_small_output_is_downscale_then_sharpen_then_jpeg() -> None:
    source = picture(3000, 4000)
    scaled, scale = downscale(source, 2048)
    expected = scaled.copy()
    detail = PhotoDetail(sharpen=PHOTO_EXPORTS[ExportPreset.SMALL].sharpen)
    apply_sharpen(expected, detail, 600 * scale, Event())

    assert not np.array_equal(expected, scaled)
    got = pixels(encode(source, ExportPreset.SMALL))
    ref = pixels(small_jpeg(expected))
    plain = pixels(small_jpeg(scaled))
    assert np.abs(got - ref).mean() < np.abs(got - plain).mean()


def test_small_edges_are_sharper_than_the_plain_downscale() -> None:
    source = picture(3000, 4000)
    plain = pixels(small_jpeg(downscale(source, 2048)[0]))
    got = pixels(encode(source, ExportPreset.SMALL))
    assert np.abs(np.diff(got, axis=1)).mean() > np.abs(np.diff(plain, axis=1)).mean()


def test_small_without_a_resize_is_not_sharpened(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_args: object) -> None:
        raise AssertionError("sharpened without a resize")

    monkeypatch.setattr(photo_encode, "apply_sharpen", fail)
    source = picture(300, 400)
    assert pixels(encode(source, ExportPreset.SMALL)).shape == (300, 400, 3)


def test_the_source_array_is_not_modified() -> None:
    source = picture(3000, 4000)
    before = source.copy()
    encode(source, ExportPreset.SMALL)
    assert np.array_equal(source, before)


@pytest.mark.parametrize("preset", [None, ExportPreset.HIGH_QUALITY, ExportPreset.LOSSLESS], ids=str)
def test_other_paths_never_sharpen(preset: ExportPreset | None, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_args: object) -> None:
        raise AssertionError("sharpened")

    monkeypatch.setattr(photo_encode, "apply_sharpen", fail)
    encode(picture(3000, 4000), preset)
