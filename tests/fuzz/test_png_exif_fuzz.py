"""Fuzz the library's PNG chunk reader and orientation writer (``library/png_exif``).

Property: any bytes either work or raise ``JpegExifError`` (a ``ValueError`` subclass) with a
short fixed message that names no path and repeats nothing from the input; nothing else escapes,
and no input is slow (the Hypothesis deadline). A well-formed PNG reads back the orientation set.
"""

import struct

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from fastfoto_linux.library import png_exif
from fastfoto_linux.library.exif_errors import JpegExifError, XmpOrientationError
from fastfoto_linux.library.xmp_scan import MAX_XMP_BYTES, names_any_orientation
from tests.fuzz.json_strategies import LEAK_MARKER
from tests.library import png_helpers as h
from tests.library.jpeg_helpers import exif_bytes

PIXELS = (np.arange(16 * 16 * 3, dtype=np.uint8) * 7).reshape(16, 16, 3)
BASE = h.make_png(PIXELS, exif=exif_bytes(6))
PLAIN = h.make_png(PIXELS)
CHUNKS = h.split(BASE)
KINDS = [b"IHDR", b"IDAT", b"IEND", b"eXIf", b"iTXt", b"tEXt", b"zTXt", b"PLTE", b"acTL", b"zzzz"]
MESSAGE_LIMIT = 200


def _exercise(data: bytes) -> None:
    try:
        layout = png_exif.Layout.of(data)
        png_exif.read_orientation(data, layout)
        png_exif.pixel_count(data, layout)
        png_exif.decoder_copy(data, layout)
        png_exif.set_orientation(data, 3, layout)
    except JpegExifError as error:
        message = str(error)
        assert message
        assert LEAK_MARKER not in message
        assert len(message) < MESSAGE_LIMIT


def test_a_well_formed_png_is_accepted() -> None:
    layout = png_exif.Layout.of(BASE)
    assert png_exif.read_orientation(BASE, layout) == 6
    assert png_exif.pixel_count(BASE, layout) == 16 * 16
    assert png_exif.decoder_copy(BASE, layout)


@given(tag=st.integers(1, 8), source=st.sampled_from([BASE, PLAIN]))
def test_set_orientation_reads_back(tag: int, source: bytes) -> None:
    assert png_exif.read_orientation(png_exif.set_orientation(source, tag)) == tag


@given(data=st.binary(max_size=300))
def test_arbitrary_bytes_never_crash(data: bytes) -> None:
    _exercise(data)
    _exercise(h.SIGNATURE + data)


@given(data=st.data())
def test_mutated_chunk_streams_never_crash(data: st.DataObject) -> None:
    chunks = list(CHUNKS)
    for _ in range(data.draw(st.integers(1, 4))):
        action = data.draw(st.sampled_from(["drop", "dup", "insert", "swap", "payload"]))
        index = data.draw(st.integers(0, len(chunks) - 1))
        if action == "drop":
            chunks.pop(index)
        elif action == "dup":
            chunks.insert(index, chunks[index])
        elif action == "swap":
            other = data.draw(st.integers(0, len(chunks) - 1))
            chunks[index], chunks[other] = chunks[other], chunks[index]
        elif action == "payload":
            chunks[index] = (chunks[index][0], data.draw(st.binary(max_size=80)))
        else:
            chunks.insert(
                index, (data.draw(st.sampled_from(KINDS)), data.draw(st.binary(max_size=80)))
            )
        if not chunks:
            chunks = list(CHUNKS)
    _exercise(h.assemble(chunks))


@given(data=st.data())
def test_flipped_bytes_including_checksums_never_crash(data: st.DataObject) -> None:
    raw = bytearray(BASE)
    for _ in range(data.draw(st.integers(1, 5))):
        raw[data.draw(st.integers(0, len(raw) - 1))] = data.draw(st.integers(0, 255))
    _exercise(bytes(raw))


@given(cut=st.integers(0, len(BASE)))
def test_every_truncation_is_refused_or_read(cut: int) -> None:
    _exercise(BASE[:cut])


@given(
    length=st.sampled_from([0, 1, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF, 2**24]),
    which=st.integers(0, len(CHUNKS) - 1),
)
def test_a_huge_or_lying_chunk_length_is_refused_without_allocating(
    length: int, which: int
) -> None:
    position = len(h.SIGNATURE)
    for index in range(which):
        position += 12 + len(CHUNKS[index][1])
    forged = BASE[:position] + struct.pack(">I", length) + BASE[position + 4 :]
    _exercise(forged)


@given(count=st.integers(4100, 4300))
def test_a_flood_of_chunks_is_refused(count: int) -> None:
    flood = h.assemble([CHUNKS[0], *[(b"tEXt", b"k\x00v")] * count, *CHUNKS[1:]])
    with pytest.raises(JpegExifError):
        png_exif.Layout.of(flood)


CARRIERS = ["itxt", "itxt-compressed", "ztxt", "text"]
CLEAN_XMP = b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF/></x:xmpmeta>'
ORIENTED_XMP = b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><a tiff:Orientation="1"/></x:xmpmeta>'
XMP_PREFIXES = [b"iTXt", b"zTXt", b"tEXt"]


@given(packet=st.binary(max_size=200), carrier=st.sampled_from(CARRIERS), tag=st.integers(1, 8))
def test_png_path_agrees_with_the_scan_on_an_arbitrary_xmp_packet(
    packet: bytes, carrier: str, tag: int
) -> None:
    png = h.with_before_idat(BASE, h.xmp_packet(packet, carrier))
    _exercise(png)
    try:
        edited = png_exif.set_orientation(png, tag)
    except XmpOrientationError:
        assert names_any_orientation(packet)
    else:
        assert not names_any_orientation(packet)
        assert png_exif.read_orientation(edited) == tag


@given(carrier=st.sampled_from(CARRIERS))
def test_xmp_with_an_orientation_is_refused_and_clean_xmp_is_kept(carrier: str) -> None:
    refused = h.with_before_idat(BASE, h.xmp_packet(ORIENTED_XMP, carrier))
    with pytest.raises(XmpOrientationError):
        png_exif.set_orientation(refused, 3)
    chunk = h.xmp_packet(CLEAN_XMP, carrier)
    edited = png_exif.set_orientation(h.with_before_idat(BASE, chunk), 3)
    assert png_exif.read_orientation(edited) == 3
    assert chunk in h.split(edited)  # the clean XMP chunk survives byte for byte


@given(
    kind=st.sampled_from(XMP_PREFIXES),
    body=st.binary(max_size=120),
    keyword=st.sampled_from([h.XMP_KEYWORD, b"xml:com.adobe.xmp", b"Raw profile type exif", b""]),
)
def test_a_text_chunk_with_a_forged_body_is_refused_or_read(
    kind: bytes, body: bytes, keyword: bytes
) -> None:
    _exercise(h.with_before_idat(BASE, (kind, keyword + b"\x00" + body)))


@given(data=st.data(), carrier=st.sampled_from(CARRIERS))
def test_a_mutated_xmp_chunk_never_crashes(data: st.DataObject, carrier: str) -> None:
    kind, payload = h.xmp_packet(ORIENTED_XMP, carrier)
    raw = bytearray(payload)
    for _ in range(data.draw(st.integers(1, 4))):
        raw[data.draw(st.integers(0, len(raw) - 1))] = data.draw(st.integers(0, 255))
    cut = data.draw(st.integers(0, len(raw)))
    _exercise(h.with_before_idat(BASE, (kind, bytes(raw[:cut]))))


@given(
    size=st.sampled_from([MAX_XMP_BYTES + 1, MAX_XMP_BYTES * 2]), carrier=st.sampled_from(CARRIERS)
)
def test_an_oversized_xmp_packet_is_refused(size: int, carrier: str) -> None:
    png = h.with_before_idat(BASE, h.xmp_packet(b" " * size, carrier))
    with pytest.raises(XmpOrientationError):
        png_exif.set_orientation(png, 3)
