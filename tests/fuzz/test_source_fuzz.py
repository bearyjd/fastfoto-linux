"""Fuzz the image entry points of the photo editor: JPEG and PNG masters with hostile metadata.

Property: ``load_source`` returns a source or raises ``PhotoEditError`` (never another error),
with a fixed message that repeats nothing of the file; a source that loads yields derivative
EXIF and XMP that keep the upright orientation and the DPI, or a ``PhotoEditError``; a malformed
ICC profile is dropped with a visible note instead of a crash.
"""

import xml.etree.ElementTree as ET
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from PIL import Image

from fastfoto_linux.library.tiff import new_block
from fastfoto_linux.output.metadata import PhotoMetadata, build_xmp
from fastfoto_linux.photo_edits import PhotoEditError, PhotoSource, load_source
from fastfoto_linux.photo_edits.metadata import (
    EXIF_NS,
    NEUTRAL_GEOMETRY,
    TIFF_NS,
    derivative_exif,
    derivative_xmp,
    frame,
)
from fastfoto_linux.photo_edits.model import MAX_SOURCE_PIXELS
from fastfoto_linux.photo_edits.png_guard import MAX_XMP_PACKET, PNG_SIGNATURE, check_png
from tests.fuzz.jpeg_builders import (
    APP1,
    APP2,
    DPI,
    EXIF_HEADER,
    ICC_HEADER,
    XMP_HEADER,
    plain_jpeg,
    segment,
    with_segments,
    with_size,
)
from tests.fuzz.json_strategies import LEAK_MARKER
from tests.photo_edits import png_helpers as h

JPEG = plain_jpeg()
NOW = datetime(2026, 1, 2, 3, 4, 5)
PNG = h.master_png()
PNG_CHUNKS = h.split(PNG)
KINDS = [b"IHDR", b"IDAT", b"IEND", b"eXIf", b"iTXt", b"iCCP", b"pHYs", b"gAMA", b"acTL", b"tRNS"]
SAFE_KIND = st.sampled_from([*KINDS, b"tEXt", b"zzzz", b"sRGB", b"bKGD"])


@pytest.fixture(scope="module")
def folder(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    yield tmp_path_factory.mktemp("fuzz-source")


def _load(folder: Path, name: str, data: bytes) -> PhotoSource | None:
    path = folder / name
    path.write_bytes(data)
    try:
        return load_source(path)
    except PhotoEditError as error:
        message = str(error)
        assert message
        assert LEAK_MARKER not in message
        assert str(folder) not in message and name not in message
        assert len(message) < 200
        return None


def _check_derivatives(source: PhotoSource) -> None:
    assert source.width * source.height <= MAX_SOURCE_PIXELS
    assert source.orientation in range(1, 9)
    try:
        exif = Image.Exif()
        exif.load(derivative_exif(source))
        assert exif[274] == 1
        assert exif[282] == pytest.approx(source.dpi_x)
        assert exif[283] == pytest.approx(source.dpi_y)
        packet = derivative_xmp(source)
    except PhotoEditError:
        return
    assert bool(packet) == bool(source.xmp), "an XMP packet is kept, and none is invented"
    _assert_xmp_is_normalised(packet, source)


def _assert_xmp_is_normalised(packet: bytes, source: PhotoSource) -> None:
    """The packet is well-formed and every geometry field it carries is upright and exact."""
    if not packet:
        return
    assert len(packet) <= MAX_XMP_PACKET
    root = ET.fromstring(packet)
    width, height, dpi_x, dpi_y = frame(source, NEUTRAL_GEOMETRY)
    expected = {
        f"{{{TIFF_NS}}}Orientation": "1",
        f"{{{TIFF_NS}}}ResolutionUnit": "2",
        f"{{{TIFF_NS}}}ImageWidth": str(width),
        f"{{{TIFF_NS}}}ImageLength": str(height),
        f"{{{EXIF_NS}}}PixelXDimension": str(width),
        f"{{{EXIF_NS}}}PixelYDimension": str(height),
    }
    resolutions = {f"{{{TIFF_NS}}}XResolution": dpi_x, f"{{{TIFF_NS}}}YResolution": dpi_y}
    for element in root.iter():
        for name, value in [*element.attrib.items(), (element.tag, element.text)]:
            if name in expected:
                assert value == expected[name], name
            elif name in resolutions:
                numerator, denominator = (value or "").split("/")
                assert int(numerator) / int(denominator) == pytest.approx(resolutions[name])


def test_xmp_geometry_fields_are_rewritten_upright(folder: Path) -> None:
    packet = (
        b"<x:xmpmeta xmlns:x='adobe:ns:meta/' xmlns:tiff='http://ns.adobe.com/tiff/1.0/'>"
        b"<tiff:Orientation>6</tiff:Orientation><tiff:XResolution>72/1</tiff:XResolution>"
        b"</x:xmpmeta>"
    )
    data = with_segments(JPEG, segment(APP1, XMP_HEADER + packet))
    source = _load(folder, "photo_0011.jpg", data)
    assert source is not None
    out = derivative_xmp(source)
    assert b">6<" not in out and b"72/1" not in out
    _assert_xmp_is_normalised(out, source)


def test_album_and_notes_survive_into_the_derivative_xmp(folder: Path) -> None:
    packet = build_xmp(
        PhotoMetadata(
            scanned_at=NOW, written_at=NOW, album="Holiday 1975", notes="Nan & Pop <left>"
        )
    )
    data = with_segments(JPEG, segment(APP1, XMP_HEADER + packet))
    source = _load(folder, "photo_0013.jpg", data)
    assert source is not None
    out = derivative_xmp(source)
    assert out
    root = ET.fromstring(out)
    assert root.tag.endswith("}xmpmeta")
    text = " ".join(root.itertext()) + " ".join(v for e in root.iter() for v in e.attrib.values())
    assert "Holiday 1975" in text
    assert "Nan & Pop <left>" in text
    _assert_xmp_is_normalised(out, source)


def _check_png(data: bytes) -> None:
    try:
        check_png(data)
    except PhotoEditError as error:
        assert str(error)
        assert LEAK_MARKER not in str(error)


def test_clean_masters_load(folder: Path) -> None:
    for name, data in (("photo_0001.jpg", JPEG), ("photo_0002.png", PNG)):
        source = _load(folder, name, data)
        assert source is not None
        assert source.dpi_x == DPI if name.endswith("jpg") else source.dpi_x == 600
        _check_derivatives(source)


@given(data=st.binary(max_size=300))
def test_arbitrary_file_bytes_never_crash(data: bytes, folder: Path) -> None:
    for name in ("photo_0003.jpg", "photo_0003.png"):
        _load(folder, name, data)


@given(data=st.binary(max_size=300))
def test_png_guard_on_arbitrary_bytes(data: bytes) -> None:
    _check_png(data)
    _check_png(PNG_SIGNATURE + data)


@given(data=st.data())
def test_png_guard_on_mutated_chunk_streams(data: st.DataObject) -> None:
    chunks = list(PNG_CHUNKS)
    for _ in range(data.draw(st.integers(1, 4))):
        action = data.draw(st.sampled_from(["drop", "dup", "insert", "swap", "ihdr"]))
        index = data.draw(st.integers(0, len(chunks) - 1))
        if action == "drop":
            chunks.pop(index)
        elif action == "dup":
            chunks.insert(index, chunks[index])
        elif action == "swap":
            other = data.draw(st.integers(0, len(chunks) - 1))
            chunks[index], chunks[other] = chunks[other], chunks[index]
        elif action == "ihdr":
            width, height = data.draw(
                st.tuples(st.integers(0, 2**32 - 1), st.integers(0, 2**32 - 1))
            )
            depth, colour = data.draw(st.tuples(st.sampled_from([1, 8, 16, 7]), st.integers(0, 7)))
            chunks[0] = (
                b"IHDR",
                h.ihdr(width, height, depth, colour, data.draw(st.integers(0, 3))),
            )
        else:
            chunks.insert(index, (data.draw(SAFE_KIND), data.draw(st.binary(max_size=60))))
        if not chunks:
            chunks = list(PNG_CHUNKS)
    _check_png(h.assemble(chunks))


@given(data=st.data())
def test_flipped_bytes_of_a_valid_png_never_crash_the_guard_or_the_loader(
    data: st.DataObject, folder: Path
) -> None:
    raw = bytearray(PNG)
    for _ in range(data.draw(st.integers(1, 4))):
        raw[data.draw(st.integers(0, len(raw) - 1))] = data.draw(st.integers(0, 255))
    _check_png(bytes(raw))
    _load(folder, "photo_0004.png", bytes(raw))


@given(
    kind=st.sampled_from([b"eXIf", b"iCCP", b"pHYs", b"iTXt"]),
    payload=st.binary(max_size=120),
)
def test_png_masters_with_hostile_metadata_chunks(
    kind: bytes, payload: bytes, folder: Path
) -> None:
    data = h.replace_kind(PNG, kind, (kind, payload))
    source = _load(folder, "photo_0005.png", data)
    if source is not None:
        _check_derivatives(source)


@given(
    exif=st.binary(max_size=200),
    xmp=st.binary(max_size=200),
    icc=st.binary(max_size=200),
)
def test_jpeg_masters_with_hostile_exif_xmp_and_icc(
    exif: bytes, xmp: bytes, icc: bytes, folder: Path
) -> None:
    data = with_segments(
        JPEG,
        segment(APP1, EXIF_HEADER + exif),
        segment(APP1, XMP_HEADER + xmp),
        segment(APP2, ICC_HEADER + icc),
    )
    source = _load(folder, "photo_0006.jpg", data)
    if source is not None:
        _check_derivatives(source)


@given(icc=st.binary(min_size=1, max_size=300))
def test_malformed_icc_is_dropped_with_a_note(icc: bytes, folder: Path) -> None:
    source = _load(folder, "photo_0007.jpg", with_segments(JPEG, segment(APP2, ICC_HEADER + icc)))
    assert source is not None, "a bad profile costs the profile, not the photo"
    noted = any("color profile" in note for note in source.warnings)
    assert noted == (source.icc_profile is None)  # kept, or dropped with a visible note


def test_a_garbage_icc_profile_is_dropped_with_a_note(folder: Path) -> None:
    data = with_segments(JPEG, segment(APP2, ICC_HEADER + b"not a profile" * 4))
    source = _load(folder, "photo_0010.jpg", data)
    assert source is not None
    assert source.icc_profile is None
    assert any("color profile" in note for note in source.warnings)


@given(
    xmp=st.sampled_from(
        [
            b"<!DOCTYPE x [<!ENTITY a 'b'>]><x/>",
            b"<a><a><a>" * 500,
            b"<x:xmpmeta xmlns:x='adobe:ns:meta/'>"
            b"<tiff:Orientation>6</tiff:Orientation></x:xmpmeta>",
            b"\xff\xfe",
            b"",
        ]
    )
)
def test_hostile_xmp_packets_are_refused_or_normalised(xmp: bytes, folder: Path) -> None:
    source = _load(folder, "photo_0008.jpg", with_segments(JPEG, segment(APP1, XMP_HEADER + xmp)))
    if source is not None:
        _check_derivatives(source)


@given(size=st.sampled_from([(65535, 65535), (8910, 10_000), (30_000, 30_000), (65535, 1400)]))
def test_jpeg_pixel_bombs_are_refused_from_the_header(size: tuple[int, int], folder: Path) -> None:
    width, height = size
    assert width * height > MAX_SOURCE_PIXELS
    assert _load(folder, "photo_0009.jpg", with_size(JPEG, width, height)) is None


def test_valid_exif_orientation_and_xmp_load(folder: Path) -> None:
    data = with_segments(JPEG, segment(APP1, EXIF_HEADER + new_block(6)))
    source = _load(folder, "photo_0012.jpg", data)
    assert source is not None
    assert source.orientation == 6
    _check_derivatives(source)
