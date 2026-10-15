"""Changing the Orientation tag appends or patches; no other Exif byte moves or changes."""

import struct

import pytest

from fastfoto_linux.library.exif_errors import ExifTooLargeError
from fastfoto_linux.library.jpeg_exif import read_orientation, set_orientation
from tests.library.jpeg_helpers import APP1, EXIF_HEADER, ORIENTATION, split_jpeg
from tests.library.tiff_helpers import (
    LATIN1_TEXT,
    LONG,
    MAKER_NOTE_TEXT,
    SHORT,
    THUMBNAIL,
    UNNORMALISED,
    TiffFixture,
    build_tiff,
    exif_block,
    jpeg_with_exif,
    read_tags,
)

MAX_PAYLOAD = 65533
ENTRY = 12
ORDERS = pytest.mark.parametrize("order", [">", "<"], ids=["big-endian", "little-endian"])
ODDNESS = pytest.mark.parametrize("odd", [False, True], ids=["even-length", "odd-length"])


def differing(first: bytes, second: bytes) -> list[int]:
    assert len(first) == len(second)
    return [i for i, (a, b) in enumerate(zip(first, second, strict=True)) if a != b]


def appended(order: str, odd: bool, tag: int = 6) -> tuple[TiffFixture, bytes]:
    """The fixture (no Orientation entry) and its Exif block after the tag was set."""
    fixture = build_tiff(order, None, odd=odd)
    return fixture, exif_block(set_orientation(jpeg_with_exif(fixture.block), tag))


@ORDERS
@ODDNESS
def test_a_missing_tag_is_added_in_an_appended_copy_of_ifd0(order: str, odd: bool) -> None:
    fixture, new = appended(order, odd)
    old = fixture.block
    assert new[:4] == old[:4]
    assert new[8 : len(old)] == old[8:]  # no other byte of the old block changed or moved
    (ifd0_at,) = struct.unpack(order + "I", new[4:8])
    assert ifd0_at >= len(old)
    assert ifd0_at % 2 == 0
    assert new[len(old) : ifd0_at] == bytes(ifd0_at - len(old))  # at most one padding byte
    assert ifd0_at - len(old) == (1 if odd else 0)
    count = fixture.entries_in_ifd0
    first = fixture.where["ifd0"] + 2
    entries = [old[first + i * ENTRY : first + (i + 1) * ENTRY] for i in range(count)]
    next_pointer = old[first + count * ENTRY : first + count * ENTRY + 4]
    entries.append(
        struct.pack(order + "HHI", ORIENTATION, SHORT, 1) + struct.pack(order + "H", 6) + b"\0\0"
    )
    entries.sort(key=lambda entry: struct.unpack(order + "H", entry[:2])[0])
    expected = struct.pack(order + "H", count + 1) + b"".join(entries) + next_pointer
    assert new[ifd0_at:] == expected  # tag order kept, IFD1 pointer kept, nothing after it


@ORDERS
@ODDNESS
def test_every_other_tag_keeps_its_exact_raw_value(order: str, odd: bool) -> None:
    fixture, new = appended(order, odd)
    before, after = read_tags(fixture.block), read_tags(new)
    assert after.pop(("ifd0", ORIENTATION)) == (SHORT, 1, struct.pack(order + "H", 6))
    assert after == before


@ORDERS
def test_thumbnail_makernote_string_and_rational_are_untouched(order: str) -> None:
    _, new = appended(order, odd=False)
    tags = read_tags(new)
    assert tags[("ifd0", 0x010E)][2] == LATIN1_TEXT  # Latin-1 "abc" + e-acute, not "abc?"
    assert tags[("ifd0", 0x011A)][2] == struct.pack(order + "II", *UNNORMALISED)  # 600/2, not 300
    (thumb_at,) = struct.unpack(order + "I", tags[("ifd1", 0x0201)][2])
    assert new[thumb_at : thumb_at + len(THUMBNAIL)] == THUMBNAIL
    maker = tags[("exif", 0x927C)][2]
    (text_at,) = struct.unpack_from(order + "I", maker, 14)  # the MakerNote's own absolute offset
    assert new[text_at : text_at + len(MAKER_NOTE_TEXT)] == MAKER_NOTE_TEXT


@ORDERS
def test_a_short_tag_is_patched_in_place_and_nothing_else_changes(order: str) -> None:
    fixture = build_tiff(order, (SHORT, 1))
    new = exif_block(set_orientation(jpeg_with_exif(fixture.block), 8))
    value_at = fixture.where["ifd0"] + 2 + ENTRY + 8
    assert len(new) == len(fixture.block)
    assert set(differing(new, fixture.block)) <= {value_at, value_at + 1}
    assert read_tags(new)[("ifd0", ORIENTATION)] == (SHORT, 1, struct.pack(order + "H", 8))


@ORDERS
def test_a_long_tag_is_patched_in_place_and_stays_a_long(order: str) -> None:
    fixture = build_tiff(order, (LONG, 1))
    data = jpeg_with_exif(fixture.block)
    assert read_orientation(data) == 1
    new = exif_block(set_orientation(data, 6))
    value_at = fixture.where["ifd0"] + 2 + ENTRY + 8
    assert len(new) == len(fixture.block)
    assert set(differing(new, fixture.block)) <= set(range(value_at, value_at + 4))
    assert read_tags(new)[("ifd0", ORIENTATION)] == (LONG, 1, struct.pack(order + "I", 6))
    assert read_orientation(set_orientation(data, 6)) == 6


def test_an_appended_tag_can_be_changed_again_in_place_and_back() -> None:
    data = jpeg_with_exif(build_tiff(">", None).block)
    first = set_orientation(data, 6)
    second = set_orientation(first, 8)
    assert len(second) == len(first)
    assert len(differing(first, second)) <= 2
    assert set_orientation(second, 6) == first


@ORDERS
def test_nothing_outside_the_exif_segment_changes_when_a_tag_is_appended(order: str) -> None:
    data = jpeg_with_exif(build_tiff(order, None).block)
    before, scan_before = split_jpeg(data)
    after, scan_after = split_jpeg(set_orientation(data, 3))
    assert scan_after == scan_before
    others = [(m, p) for m, p in before if not (m == APP1 and p.startswith(EXIF_HEADER))]
    assert [(m, p) for m, p in after if not (m == APP1 and p.startswith(EXIF_HEADER))] == others


def padded_to(length: int) -> bytes:
    """The even-length fixture block with trailing bytes so that it is ``length`` long."""
    block = build_tiff(">", None).block
    return block + bytes(length - len(block))


def test_the_whole_payload_including_the_appended_ifd_must_fit_one_segment() -> None:
    entries = build_tiff(">", None).entries_in_ifd0
    growth = 2 + (entries + 1) * ENTRY + 4
    fits = MAX_PAYLOAD - len(EXIF_HEADER) - growth
    assert fits % 2 == 0
    result = set_orientation(jpeg_with_exif(padded_to(fits)), 6)
    assert len(exif_block(result)) + len(EXIF_HEADER) == MAX_PAYLOAD
    with pytest.raises(ExifTooLargeError) as raised:
        set_orientation(jpeg_with_exif(padded_to(fits + 1)), 6)  # the padding byte tips it over
    assert raised.value.reason == "exif-too-large"
