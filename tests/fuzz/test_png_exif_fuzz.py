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
from fastfoto_linux.library.exif_errors import JpegExifError
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
