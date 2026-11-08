"""Fuzz the JPEG/EXIF segment and TIFF readers of the library.

Property: any bytes either work or raise ``JpegExifError`` (a ``ValueError`` with a fixed
message); nothing else escapes and no input is slow. For a well-formed JPEG, setting the
Orientation reads back and changes nothing after the segments.
"""

import contextlib

import pytest
from hypothesis import given
from hypothesis import strategies as st

from fastfoto_linux.library import jpeg_exif
from fastfoto_linux.library.exif_errors import JpegExifError
from fastfoto_linux.library.tiff import inspect_tiff, new_block
from tests.fuzz.jpeg_builders import (
    APP1,
    EXIF_HEADER,
    plain_jpeg,
    segment,
    with_segments,
)
from tests.fuzz.json_strategies import LEAK_MARKER

BASE = plain_jpeg()
TIFF_SEEDS = [new_block(tag) for tag in range(1, 9)]


def _exercise(data: bytes) -> None:
    """Every public reader on ``data``: a typed refusal or a result, never another error."""
    try:
        layout = jpeg_exif.Layout.of(data)
        jpeg_exif.read_orientation(data, layout)
        jpeg_exif.pixel_count(data, layout)
        jpeg_exif.decoder_copy(data, layout)
        jpeg_exif.set_orientation(data, 6, layout)
    except JpegExifError as error:
        assert str(error)
        assert LEAK_MARKER not in str(error)


def _flip(raw: bytes, data: st.DataObject, limit: int = 6) -> bytes:
    mutable = bytearray(raw)
    for _ in range(data.draw(st.integers(1, limit))):
        mutable[data.draw(st.integers(0, len(mutable) - 1))] = data.draw(st.integers(0, 255))
    return bytes(mutable)


def test_a_well_formed_jpeg_is_accepted() -> None:
    layout = jpeg_exif.Layout.of(BASE)
    assert jpeg_exif.pixel_count(BASE, layout) > 0
    assert jpeg_exif.decoder_copy(BASE, layout)


@given(data=st.binary(max_size=400))
def test_arbitrary_bytes_never_crash(data: bytes) -> None:
    _exercise(data)


@given(data=st.binary(max_size=400))
def test_arbitrary_bytes_after_soi_never_crash(data: bytes) -> None:
    _exercise(b"\xff\xd8" + data)


@given(block=st.binary(max_size=200))
def test_arbitrary_tiff_blocks_are_checked_or_refused(block: bytes) -> None:
    with contextlib.suppress(JpegExifError):
        inspect_tiff(block)


@given(data=st.data())
def test_flipped_tiff_blocks_are_checked_or_refused(data: st.DataObject) -> None:
    block = _flip(data.draw(st.sampled_from(TIFF_SEEDS)), data)
    with contextlib.suppress(JpegExifError):
        inspect_tiff(block)
    _exercise(with_segments(BASE, segment(APP1, EXIF_HEADER + block)))


@given(payload=st.binary(max_size=200), marker=st.integers(0xE0, 0xEF))
def test_arbitrary_application_segments_never_crash(payload: bytes, marker: int) -> None:
    _exercise(with_segments(BASE, segment(marker, payload)))


@given(data=st.data())
def test_flipped_bytes_of_a_valid_jpeg_never_crash(data: st.DataObject) -> None:
    raw = with_segments(BASE, segment(APP1, EXIF_HEADER + TIFF_SEEDS[5]))
    mutated = bytearray(raw)
    scan = jpeg_exif.Layout.of(raw).scan_start
    for _ in range(data.draw(st.integers(1, 6))):
        mutated[data.draw(st.integers(0, scan - 1))] = data.draw(st.integers(0, 255))
    _exercise(bytes(mutated))


@given(tag=st.integers(1, 8), initial=st.one_of(st.none(), st.integers(1, 8)))
def test_set_orientation_reads_back_and_touches_only_the_exif_segment(
    tag: int, initial: int | None
) -> None:
    jpeg = BASE
    if initial is not None:
        jpeg = with_segments(BASE, segment(APP1, EXIF_HEADER + new_block(initial)))
    edited = jpeg_exif.set_orientation(jpeg, tag)
    assert jpeg_exif.read_orientation(edited) == tag
    assert (
        edited[jpeg_exif.Layout.of(edited).scan_start :]
        == jpeg[jpeg_exif.Layout.of(jpeg).scan_start :]
    )


@given(count=st.integers(1100, 1400))
def test_marker_flood_is_refused_by_the_segment_limit(count: int) -> None:
    flood = b"\xff\xd8" + b"\xff\xfe\x00\x02" * count + b"\xff\xda"
    with pytest.raises(JpegExifError):
        jpeg_exif.Layout.of(flood)
