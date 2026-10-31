"""Pins today's photo output for the no-preset path: the bytes equal the legacy encoder call.

Export presets must leave this path byte-identical, so these tests compare ``write_photo`` and
``write_unprocessed`` files with a direct ``Image.save`` made exactly as the writer made it before
presets existed (JPEG, the given quality, 4:4:4, scan DPI, EXIF and XMP built from the metadata).
"""

import io
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

from fastfoto_linux.output import writer
from fastfoto_linux.output.metadata import PhotoDate, PhotoMetadata, build_exif, build_xmp
from fastfoto_linux.output.writer import write_photo, write_unprocessed
from tests._output_helpers import DPI, make_root, names

NOW = datetime(2024, 5, 6, 7, 8, 9)
SCANNED = datetime(2024, 5, 1, 2, 3, 4)
NOTES = "Beach day, Grandma é & Zürich"
ALBUM = "Summer"
DATE = PhotoDate(1975, 6, 14)


def textured(size: tuple[int, int] = (64, 96), seed: int = 1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    height, width = size
    ramp = np.linspace(0, 255, width, dtype=np.float32)[None, :, None]
    noise = rng.integers(0, 40, size=(height, width, 3))
    return np.clip(ramp + noise, 0, 255).astype(np.uint8)


def legacy_jpeg(array: np.ndarray, *, dpi: int = DPI, quality: int = 95) -> bytes:
    meta = PhotoMetadata(scanned_at=SCANNED, written_at=NOW, album=ALBUM, notes=NOTES, date=DATE)
    buffer = io.BytesIO()
    Image.fromarray(array).save(
        buffer,
        "JPEG",
        quality=quality,
        subsampling=0,
        dpi=(dpi, dpi),
        exif=build_exif(meta),
        xmp=build_xmp(meta),
    )
    return buffer.getvalue()


def write(tmp_path: Path, monkeypatch, **extra):
    monkeypatch.setattr(writer, "_now", lambda: NOW)
    return write_photo(
        textured(),
        dpi=DPI,
        output_root=make_root(tmp_path),
        album=ALBUM,
        date=DATE,
        notes=NOTES,
        scanned_at=SCANNED,
        **extra,
    )


def test_default_original_equals_the_legacy_encoder_call(tmp_path, monkeypatch) -> None:
    result = write(tmp_path, monkeypatch)

    assert result.original is not None
    assert result.original.read_bytes() == legacy_jpeg(textured())


def test_a_custom_quality_equals_the_legacy_encoder_call(tmp_path, monkeypatch) -> None:
    result = write(tmp_path, monkeypatch, quality=80)

    assert result.original is not None
    assert result.original.read_bytes() == legacy_jpeg(textured(), quality=80)


def test_enhanced_and_back_files_use_the_same_encoder(tmp_path, monkeypatch) -> None:
    enhanced, back = textured(seed=2), textured(seed=3)
    result = write(tmp_path, monkeypatch, enhanced=enhanced, back=back)

    assert result.enhanced is not None and result.back is not None
    assert result.enhanced.read_bytes() == legacy_jpeg(enhanced)
    assert result.back.read_bytes() == legacy_jpeg(back)
    assert names(result.directory) == [
        "Summer_0001.jpg",
        "Summer_0001_a.jpg",
        "Summer_0001_b.jpg",
    ]


def test_whole_pages_use_the_same_encoder(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(writer, "_now", lambda: NOW)
    back = textured(seed=4)
    result = write_unprocessed(
        textured(),
        dpi=DPI,
        output_root=make_root(tmp_path),
        reason="no photo found",
        back=back,
        album=ALBUM,
        date=DATE,
        notes=NOTES,
        scanned_at=SCANNED,
    )

    assert result.original is not None and result.back is not None
    assert result.original.read_bytes() == legacy_jpeg(textured())
    assert result.back.read_bytes() == legacy_jpeg(back)
    assert names(result.directory) == [
        "Summer_0001_unprocessed.jpg",
        "Summer_0001_unprocessed_b.jpg",
    ]
