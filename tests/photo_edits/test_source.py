"""Source identity, canonical coordinates and metadata remain explicit."""

import hashlib
from pathlib import Path

import numpy as np
import pytest
from PIL import ExifTags, Image

from fastfoto_linux.photo_edits import PhotoEditError, load_source
from tests.photo_edits.helpers import DPI, HEIGHT, WIDTH, pixels, source_at


def test_source_hashes_exact_bytes_and_never_rewrites_original(tmp_path: Path) -> None:
    existing = source_at(tmp_path)
    before = existing.path.read_bytes()
    source = load_source(existing.path)
    assert source.path == existing.path
    assert source.sha256 == hashlib.sha256(before).hexdigest()
    assert source.byte_size == len(before)
    assert (source.width, source.height) == (WIDTH, HEIGHT)
    assert np.array_equal(source.pixels, existing.pixels)
    assert not source.pixels.flags.writeable
    assert existing.path.read_bytes() == before


def test_source_hash_mismatch_is_an_explicit_error(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    with pytest.raises(PhotoEditError, match=r"source|hash|changed"):
        load_source(source.path, expected_sha256="0" * 64)


@pytest.mark.parametrize("orientation", [1, 3, 6, 8])
def test_orientation_normalizes_pixels_and_axis_dpi(tmp_path: Path, orientation: int) -> None:
    path = tmp_path / "oriented.jpg"
    exif = Image.Exif()
    exif[ExifTags.Base.Orientation] = orientation
    Image.fromarray(pixels()).save(path, exif=exif, dpi=(300, 600))
    source = load_source(path)
    axes_swapped = orientation in {6, 8}
    expected_size = (HEIGHT, WIDTH) if axes_swapped else (WIDTH, HEIGHT)
    expected_dpi = (600, 300) if axes_swapped else (300, 600)
    assert (source.width, source.height) == expected_size
    assert (source.dpi_x, source.dpi_y) == expected_dpi
    assert source.effective_dpi == 600
    assert source.orientation == orientation
    assert source.pixels.shape[:2] == expected_size[::-1]


def test_missing_dpi_uses_recorded_fallback_and_warning(tmp_path: Path) -> None:
    path = tmp_path / "no-resolution.jpg"
    Image.fromarray(pixels()).save(path)
    source = load_source(path)
    assert source.effective_dpi == DPI
    assert source.warnings


def test_source_captures_existing_exif_xmp_and_profile_bytes(tmp_path: Path) -> None:
    path = tmp_path / "metadata.jpg"
    exif = Image.Exif()
    exif[ExifTags.Base.ImageDescription] = "Synthetic metadata fixture"
    xmp = b'<x:xmpmeta xmlns:x="adobe:ns:meta/"/>'
    Image.fromarray(pixels()).save(path, exif=exif, xmp=xmp, dpi=(DPI, DPI))
    source = load_source(path)
    captured = Image.Exif()
    captured.load(source.exif)
    assert captured[ExifTags.Base.ImageDescription] == "Synthetic metadata fixture"
    assert source.xmp == xmp


def test_invalid_image_is_reported_without_touching_it(tmp_path: Path) -> None:
    path = tmp_path / "broken.jpg"
    path.write_bytes(b"synthetic invalid jpeg")
    with pytest.raises(PhotoEditError):
        load_source(path)
    assert path.read_bytes() == b"synthetic invalid jpeg"
