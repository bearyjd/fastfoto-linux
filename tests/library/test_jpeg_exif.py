"""Changing the Orientation tag must leave every other byte of the JPEG alone."""

import io
import struct

import pytest
from PIL import ExifTags, Image

from fastfoto_linux.library.exif_errors import (
    ExifMalformedError,
    ExifTooLargeError,
    JpegExifError,
    NotAJpegError,
)
from fastfoto_linux.library.jpeg_exif import read_orientation, set_orientation
from tests.face_images import load_astronaut
from tests.library.jpeg_helpers import (
    APP0,
    APP1,
    APP2,
    DATE_ORIGINAL,
    EXIF_HEADER,
    ICC_PAYLOAD,
    ORIENTATION,
    SOI,
    XMP_PACKET,
    exif_bytes,
    exif_payloads,
    make_jpeg,
    oversized_exif,
    segment,
    split_jpeg,
    stored_array,
)

TIFF_LONG = 4


def photo(tag: int | None, **options: bool) -> bytes:
    """The portrait with Exif carrying ``tag``; ``None``: no Exif segment at all."""
    exif = None if tag is None else exif_bytes(tag, date=True)
    return make_jpeg(load_astronaut(), exif=exif, **options)


def differing_positions(first: bytes, second: bytes) -> list[int]:
    assert len(first) == len(second)
    return [i for i, (a, b) in enumerate(zip(first, second, strict=True)) if a != b]


def raw_exif_with_long_orientation(value: int) -> bytes:
    """A minimal big-endian Exif whose Orientation is a LONG instead of the usual SHORT."""
    entry = struct.pack(">HHII", ORIENTATION, TIFF_LONG, 1, value)
    return EXIF_HEADER + b"MM\x00*" + struct.pack(">I", 8) + struct.pack(">H", 1) + entry + bytes(4)


def with_exif_segment(data: bytes, payload: bytes) -> bytes:
    """``data`` (a JPEG without Exif) with ``payload`` as an APP1 right after the JFIF segment."""
    jfif_end = 4 + struct.unpack(">H", data[4:6])[0]
    return data[:jfif_end] + segment(APP1, payload) + data[jfif_end:]


# --- reading --------------------------------------------------------------------------


@pytest.mark.parametrize("tag", [1, 3, 6, 8, 5])
def test_reads_the_tag(tag: int) -> None:
    assert read_orientation(photo(tag)) == tag


def test_no_exif_or_no_tag_reads_as_none() -> None:
    assert read_orientation(photo(None)) is None
    assert read_orientation(make_jpeg(load_astronaut(), exif=exif_bytes(None))) is None


def test_reads_a_long_typed_tag() -> None:
    data = with_exif_segment(photo(None), raw_exif_with_long_orientation(6))
    assert read_orientation(data) == 6


# --- replacing a tag that exists ------------------------------------------------------


@pytest.mark.parametrize("little_endian", [False, True])
@pytest.mark.parametrize(("old", "new"), [(1, 6), (6, 8), (8, 3), (3, 1), (1, 8)])
def test_an_existing_tag_is_patched_in_place(old: int, new: int, little_endian: bool) -> None:
    data = make_jpeg(load_astronaut(), exif=exif_bytes(old, date=True, little_endian=little_endian))
    result = set_orientation(data, new)
    assert read_orientation(result) == new
    changed = differing_positions(data, result)
    assert 1 <= len(changed) <= 2
    exif_start = data.index(EXIF_HEADER)
    exif_end = exif_start + len(exif_payloads(data)[0])
    assert all(exif_start <= i < exif_end for i in changed)


def test_setting_the_same_tag_returns_identical_bytes() -> None:
    data = photo(6)
    assert set_orientation(data, 6) == data


def test_going_back_restores_the_original_bytes() -> None:
    data = photo(6)
    assert set_orientation(set_orientation(data, 8), 6) == data


def test_a_long_typed_tag_is_patched_in_place() -> None:
    data = with_exif_segment(photo(None), raw_exif_with_long_orientation(6))
    result = set_orientation(data, 8)
    assert read_orientation(result) == 8
    value_at = data.index(EXIF_HEADER) + len(EXIF_HEADER) + 8 + 2 + 8  # IFD0 entry 0, its value
    assert set(differing_positions(data, result)) <= set(range(value_at, value_at + 4))
    assert stored_array(result).tobytes() == stored_array(data).tobytes()


# --- pixels and every other byte ------------------------------------------------------


@pytest.mark.parametrize("start", [None, 1, 6])
@pytest.mark.parametrize("new", [3, 6, 8])
def test_decoded_pixels_are_bit_identical(start: int | None, new: int) -> None:
    data = photo(start)
    result = set_orientation(data, new)
    with Image.open(io.BytesIO(data)) as before, Image.open(io.BytesIO(result)) as after:
        assert after.tobytes() == before.tobytes()  # no exif_transpose: the stored pixels


@pytest.mark.parametrize("start", [None, 1, 6])
def test_every_segment_but_the_exif_one_and_the_scan_are_identical(start: int | None) -> None:
    data = photo(start, xmp=True, icc=True)
    result = set_orientation(data, 8)
    before, scan_before = split_jpeg(data)
    after, scan_after = split_jpeg(result)
    assert scan_after == scan_before  # entropy-coded data and everything after it
    keep = [(m, p) for m, p in before if not (m == APP1 and p.startswith(EXIF_HEADER))]
    assert [(m, p) for m, p in after if not (m == APP1 and p.startswith(EXIF_HEADER))] == keep
    assert (APP1, XMP_PACKET) in after
    assert (APP2, ICC_PAYLOAD) in after


@pytest.mark.parametrize("start", [None, 1])
def test_pillow_reads_every_exif_field_after_a_patch_or_an_append(start: int | None) -> None:
    data = make_jpeg(load_astronaut(), exif=exif_bytes(start, date=True, ImageDescription="hi"))
    with Image.open(io.BytesIO(set_orientation(data, 6))) as image:
        exif = image.getexif()
        assert exif[ORIENTATION] == 6
        assert exif[ExifTags.Base.Make] == "TestCam"
        assert exif[ExifTags.Base.ImageDescription] == "hi"
        assert exif.get_ifd(ExifTags.IFD.Exif)[ExifTags.Base.DateTimeOriginal] == DATE_ORIGINAL


def test_adding_a_missing_tag_keeps_exif_xmp_and_icc() -> None:
    data = make_jpeg(load_astronaut(), exif=exif_bytes(None, date=True), xmp=True, icc=True)
    result = set_orientation(data, 6)
    segments, _ = split_jpeg(result)
    assert (APP1, XMP_PACKET) in segments
    assert (APP2, ICC_PAYLOAD) in segments
    with Image.open(io.BytesIO(result)) as image:
        assert image.info["icc_profile"] == ICC_PAYLOAD[14:]
        assert image.getexif().get_ifd(ExifTags.IFD.Exif)[36867] == DATE_ORIGINAL


# --- a file without Exif --------------------------------------------------------------


def test_a_file_without_exif_gets_one_after_the_jfif_segment() -> None:
    data = make_jpeg(load_astronaut())
    result = set_orientation(data, 6)
    assert read_orientation(result) == 6
    before, scan_before = split_jpeg(data)
    after, scan_after = split_jpeg(result)
    assert scan_after == scan_before
    assert [m for m, _ in after[:2]] == [APP0, APP1]
    assert after[0] == before[0]
    assert after[2:] == before[1:]
    assert len(exif_payloads(result)) == 1


def test_a_file_without_jfif_gets_exif_right_after_soi() -> None:
    data = make_jpeg(load_astronaut())
    jfif_end = 4 + struct.unpack(">H", data[4:6])[0]
    bare = data[:2] + data[jfif_end:]
    result = set_orientation(bare, 8)
    assert result[:2] == SOI
    assert result[2:4] == bytes([0xFF, APP1])
    assert read_orientation(result) == 8
    assert split_jpeg(result)[1] == split_jpeg(bare)[1]


# --- limits and bad input -------------------------------------------------------------


def test_a_nearly_full_exif_segment_is_still_patched_in_place() -> None:
    data = make_jpeg(load_astronaut(), exif=oversized_exif(tag=6))
    assert read_orientation(set_orientation(data, 8)) == 8


def test_an_appended_ifd_that_would_overflow_the_segment_is_refused() -> None:
    data = make_jpeg(load_astronaut(), exif=oversized_exif(tag=None))
    with pytest.raises(ExifTooLargeError) as raised:
        set_orientation(data, 6)
    assert raised.value.reason == "exif-too-large"


@pytest.mark.parametrize("tag", [0, 9, -1])
def test_a_tag_outside_1_to_8_is_a_value_error(tag: int) -> None:
    with pytest.raises(ValueError, match="1 and 8"):
        set_orientation(photo(6), tag)


def garbled_cases() -> dict[str, bytes]:
    good = photo(6)
    segments, _ = split_jpeg(good)
    header_end = 2 + sum(4 + len(p) for _, p in segments[:1])
    no_scan = good[:header_end] + b"\xff\xd9"
    junk_tiff = segment(APP1, EXIF_HEADER + b"this is not a TIFF header at all")
    bad_offset = segment(APP1, EXIF_HEADER + b"MM\x00*" + struct.pack(">I", 0x00FFFFFF))
    return {
        "not a jpeg": b"definitely not a jpeg",
        "empty": b"",
        "cut inside a segment": good[:40],
        "segment longer than the file": good[:2] + b"\xff\xe0\xff\xf0" + b"JFIF\x00",
        "no scan": no_scan,
        "marker byte missing": good[:2] + b"\x00\x00\x00\x10" + good[6:60],
        "tiff header is junk": good[:2] + junk_tiff + good[2:],
        "ifd offset outside segment": good[:2] + bad_offset + good[2:],
    }


@pytest.mark.parametrize("name", sorted(garbled_cases()))
def test_garbled_files_raise_a_clear_error_and_nothing_else(name: str) -> None:
    data = garbled_cases()[name]
    snapshot = bytes(data)
    with pytest.raises(JpegExifError) as raised:
        set_orientation(data, 8)
    assert raised.value.reason in {"unreadable", "bad-exif", "exif-malformed"}
    assert str(raised.value)
    assert data == snapshot


def test_error_reasons_are_short_codes() -> None:
    assert JpegExifError.reason == "bad-exif"
    assert NotAJpegError.reason == "unreadable"
    assert ExifTooLargeError.reason == "exif-too-large"
    assert ExifMalformedError.reason == "exif-malformed"


def test_read_orientation_rejects_garbled_files_too() -> None:
    with pytest.raises(NotAJpegError):
        read_orientation(b"nope")
    with pytest.raises(JpegExifError):
        read_orientation(garbled_cases()["tiff header is junk"])


def test_a_result_that_pillow_cannot_open_is_never_returned() -> None:
    no_frame_header = SOI + b"\xff\xda\x00\x02" + bytes(8)  # parses as segments, has no image
    with pytest.raises(JpegExifError, match="re-read"):
        set_orientation(no_frame_header, 6)
