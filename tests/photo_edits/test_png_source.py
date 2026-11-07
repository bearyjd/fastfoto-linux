"""PNG masters: accepted metadata, and every refusal happens before pixels are decoded."""

import zlib
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from fastfoto_linux.photo_edits import PhotoEditError, load_source
from fastfoto_linux.photo_edits.model import MAX_SOURCE_PIXELS
from fastfoto_linux.photo_edits.png_guard import check_png
from tests.photo_edits import png_helpers as h

BIG = 65_534


def _load(tmp_path: Path, data: bytes):
    path = tmp_path / "photo_0001.png"
    path.write_bytes(data)
    return load_source(path)


def _refused(tmp_path: Path, data: bytes, match: str) -> None:
    with pytest.raises(PhotoEditError, match=match):
        _load(tmp_path, data)


def test_lossless_master_loads_with_dpi_xmp_and_exif(tmp_path: Path) -> None:
    source = _load(tmp_path, h.master_png())
    assert (source.width, source.height) == (h.WIDTH, h.HEIGHT)
    assert source.dpi_x == source.dpi_y == source.effective_dpi == 600
    assert isinstance(source.dpi_x, float) and not source.warnings
    assert source.xmp == h.XMP
    assert source.exif
    assert np.array_equal(source.pixels, h.pixels())
    assert source.orientation == 1


def test_png_without_physical_size_uses_the_fallback_note(tmp_path: Path) -> None:
    source = _load(tmp_path, h.saved("RGB"))
    assert source.effective_dpi == 300
    assert source.warnings


def test_png_with_unknown_phys_unit_uses_the_fallback_note(tmp_path: Path) -> None:
    phys = (b"pHYs", (11811).to_bytes(4, "big") * 2 + b"\x00")
    source = _load(tmp_path, h.with_chunks(h.saved("RGB"), before_idat=(phys,)))
    assert source.effective_dpi == 300
    assert source.warnings


def test_jpeg_still_loads_and_png_signature_is_not_trusted_from_the_suffix(tmp_path: Path) -> None:
    path = tmp_path / "photo_0001.jpg"
    Image.fromarray(h.pixels()).save(path, "PNG")
    assert load_source(path).width == h.WIDTH


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(h.saved("RGBA"), id="rgba"),
        pytest.param(h.saved("P"), id="palette"),
        pytest.param(h.saved("L"), id="grey"),
        pytest.param(h.saved("I;16"), id="grey16"),
        pytest.param(
            h.replace_ihdr(h.master_png(), h.ihdr(h.WIDTH, h.HEIGHT, depth=16)), id="rgb16"
        ),
    ],
)
def test_only_8_bit_rgb_is_accepted(tmp_path: Path, data: bytes) -> None:
    _refused(tmp_path, data, "8-bit RGB")


def test_apng_is_refused(tmp_path: Path) -> None:
    actl = (b"acTL", (1).to_bytes(4, "big") * 2)
    _refused(tmp_path, h.with_chunks(h.master_png(), before_idat=(actl,)), "animated")


def test_huge_claimed_size_with_valid_crc_is_refused_without_decoding(tmp_path: Path) -> None:
    header = h.ihdr(30_000, 30_000)
    assert MAX_SOURCE_PIXELS < 30_000 * 30_000
    _refused(tmp_path, h.replace_ihdr(h.master_png(), header), "too many pixels")


def test_zero_size_is_refused(tmp_path: Path) -> None:
    _refused(tmp_path, h.replace_ihdr(h.master_png(), h.ihdr(0, h.HEIGHT)), "not a supported")


def test_bad_ihdr_crc_is_refused(tmp_path: Path) -> None:
    good = h.master_png()
    start = len(h.SIGNATURE) + 8 + 13
    bad = good[:start] + bytes(b ^ 0xFF for b in good[start : start + 4]) + good[start + 4 :]
    _refused(tmp_path, bad, "not a supported")


def test_ihdr_must_come_first_and_be_13_bytes(tmp_path: Path) -> None:
    chunks = h.split(h.master_png())
    _refused(tmp_path, h.assemble([(b"tEXt", b"a\x00b"), *chunks]), "not a supported")
    _refused(
        tmp_path,
        h.assemble([(b"IHDR", h.ihdr(h.WIDTH, h.HEIGHT) + b"\x00"), *chunks[1:]]),
        "not a supported",
    )


def test_two_exif_chunks_are_refused(tmp_path: Path) -> None:
    exif = next(data for kind, data in h.split(h.master_png()) if kind == b"eXIf")
    data = h.with_chunks(h.master_png(), before_idat=((b"eXIf", exif),))
    _refused(tmp_path, data, "metadata")


def test_exif_after_idat_is_refused(tmp_path: Path) -> None:
    chunks = [c for c in h.split(h.master_png()) if c[0] != b"eXIf"]
    exif = (b"eXIf", b"MM\x00*\x00\x00\x00\x08\x00\x00")
    data = h.with_chunks(h.assemble(chunks), after_idat=(exif,))
    _refused(tmp_path, data, "metadata")


def test_oversized_exif_is_refused_and_the_limit_is_inclusive(tmp_path: Path) -> None:
    base = h.assemble([c for c in h.split(h.master_png()) if c[0] != b"eXIf"])
    _refused(tmp_path, h.with_chunks(base, before_idat=((b"eXIf", b"\x00" * BIG),)), "metadata")
    ok = h.with_chunks(
        base, before_idat=((b"eXIf", b"MM\x00*\x00\x00\x00\x08" + b"\x00" * (BIG - 10)),)
    )
    check_png(ok)


def test_oversized_xmp_is_refused(tmp_path: Path) -> None:
    base = h.assemble([c for c in h.split(h.master_png()) if c[0] != b"iTXt"])
    data = b"XML:com.adobe.xmp\x00\x00\x00\x00\x00" + b"x" * BIG
    _refused(tmp_path, h.with_chunks(base, before_idat=((b"iTXt", data),)), "metadata")


def test_oversized_compressed_text_chunk_is_a_clean_refusal(tmp_path: Path) -> None:
    bomb = b"k\x00\x00" + zlib.compress(b"\x00" * 5_000_000)
    data = h.with_chunks(h.master_png(), before_idat=((b"zTXt", bomb),))
    _refused(tmp_path, data, "not a supported")


def test_chunk_count_is_capped(tmp_path: Path) -> None:
    filler = tuple((b"tEXt", b"k\x00v") for _ in range(4100))
    _refused(tmp_path, h.with_chunks(h.master_png(), before_idat=filler), "too many")


def test_truncated_or_unterminated_streams_are_refused(tmp_path: Path) -> None:
    good = h.master_png()
    _refused(tmp_path, good[:-12], "not a supported")
    _refused(tmp_path, good[:30], "not a supported")
    _refused(tmp_path, h.SIGNATURE, "not a supported")


def test_declared_chunk_length_beyond_the_file_is_refused(tmp_path: Path) -> None:
    good = h.master_png()
    pos = len(h.SIGNATURE) + 25
    bad = good[:pos] + (0x7FFFFFFF).to_bytes(4, "big") + good[pos + 4 :]
    _refused(tmp_path, bad, "not a supported")


def test_error_messages_never_name_the_path(tmp_path: Path) -> None:
    with pytest.raises(PhotoEditError) as caught:
        _load(tmp_path, h.saved("RGBA"))
    assert str(tmp_path) not in str(caught.value)
