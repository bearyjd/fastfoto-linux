"""Exif blocks that are odd but harmless are edited; only what is really read is checked."""

import struct

import pytest

from fastfoto_linux.library.decide import decide_file
from fastfoto_linux.library.exif_errors import ExifMalformedError, JpegExifError
from fastfoto_linux.library.jpeg_exif import read_orientation, set_orientation
from fastfoto_linux.library.plan import Action
from tests.library.jpeg_helpers import write_file
from tests.library.tiff_edge_helpers import (
    ASCII,
    BEYOND_THE_BLOCK,
    EXIF_POINTER,
    GPS_POINTER,
    LONG,
    UNKNOWN_TYPE,
    block,
    entry,
    ifd,
    orientation,
    sub_ifd_entry,
    tail_at,
)
from tests.library.tiff_helpers import exif_block, jpeg_with_exif

ORDERS = pytest.mark.parametrize("order", ["<", ">"])
NEW_TAG = 6
DUPLICATE_REASON = "exif-duplicate-orientation"


def edited(tiff: bytes) -> bytes:
    """The Exif block after the Orientation was set; the edit has verified itself with Pillow."""
    result = set_orientation(jpeg_with_exif(tiff), NEW_TAG)
    assert read_orientation(result) == NEW_TAG
    return exif_block(result)


@ORDERS
def test_an_entry_of_an_unknown_type_is_counted_in_bytes_and_does_not_stop_the_edit(
    order: str,
) -> None:
    inline = entry(order, 0x9998, UNKNOWN_TYPE, 3, b"abc")
    outside = entry(order, 0x9999, UNKNOWN_TYPE, 8, tail_at(3))
    tiff = block(order, [orientation(order, 1), inline, outside], tail=b"12345678")
    assert read_orientation(jpeg_with_exif(tiff)) == 1
    new = edited(tiff)
    assert len(new) == len(tiff) and new.endswith(b"12345678")


@ORDERS
def test_an_unknown_type_whose_values_run_past_the_block_is_still_refused(order: str) -> None:
    tiff = block(order, [entry(order, 0x9999, UNKNOWN_TYPE, 8, BEYOND_THE_BLOCK)])
    with pytest.raises(ExifMalformedError):
        read_orientation(jpeg_with_exif(tiff))


@ORDERS
def test_a_known_type_with_a_count_that_does_not_fit_is_still_refused(order: str) -> None:
    tiff = block(order, [entry(order, 0x010E, ASCII, 100_000, tail_at(1))])
    with pytest.raises(ExifMalformedError):
        read_orientation(jpeg_with_exif(tiff))


@ORDERS
def test_an_entry_with_no_values_is_fine(order: str) -> None:
    tiff = block(order, [entry(order, 0x010E, ASCII, 0, 0), orientation(order, 3)])
    assert read_orientation(jpeg_with_exif(tiff)) == 3
    assert edited(tiff)[: -0 or None] != b""


@ORDERS
@pytest.mark.parametrize("pointer", [EXIF_POINTER, GPS_POINTER])
def test_a_sub_ifd_whose_next_pointer_is_junk_does_not_matter(order: str, pointer: int) -> None:
    sub = ifd(order, [sub_ifd_entry(order)], BEYOND_THE_BLOCK)
    tiff = block(order, [entry(order, pointer, LONG, 1, tail_at(1))], tail=sub)
    new = edited(tiff)
    assert new[8 : len(tiff)] == tiff[8:]  # the old bytes, sub-IFD included, have not moved


@ORDERS
@pytest.mark.parametrize("pointer", [EXIF_POINTER, GPS_POINTER])
def test_a_sub_ifd_pointer_of_zero_means_there_is_none(order: str, pointer: int) -> None:
    tiff = block(order, [entry(order, pointer, LONG, 1, 0), orientation(order, 8)])
    assert read_orientation(jpeg_with_exif(tiff)) == 8
    assert len(edited(tiff)) == len(tiff)


@ORDERS
def test_a_next_ifd_pointer_past_the_end_is_zero_in_the_copy_of_ifd0(order: str) -> None:
    """Left in the copy it would point into the bytes appended after it (see the pointer tests)."""
    tiff = block(order, [entry(order, 0x010E, ASCII, 4, b"abc\0")], ifd0_next=BEYOND_THE_BLOCK)
    new = edited(tiff)
    assert new.startswith(tiff[:4]) and new[8 : len(tiff)] == tiff[8:]  # old bytes unmoved
    assert new[-4:] == bytes(4)


@ORDERS
def test_a_next_ifd_pointer_past_the_end_is_untouched_when_the_tag_is_patched_in_place(
    order: str,
) -> None:
    tiff = block(order, [orientation(order, 1)], ifd0_next=BEYOND_THE_BLOCK)
    new = edited(tiff)
    assert len(new) == len(tiff)
    assert new[-4:] == struct.pack(order + "I", BEYOND_THE_BLOCK)


@ORDERS
def test_the_junk_after_ifd1_is_not_followed(order: str) -> None:
    ifd1 = ifd(order, [], BEYOND_THE_BLOCK)  # IFD1 claims a successor; only IFD0 -> IFD1 counts
    tiff = block(order, [orientation(order, 1)], ifd0_next=tail_at(1), tail=ifd1)
    assert edited(tiff).endswith(ifd1)


@ORDERS
def test_an_ifd_that_leads_back_to_ifd0_is_still_refused(order: str) -> None:
    tiff = block(order, [orientation(order, 1)], ifd0_next=8)
    with pytest.raises(ExifMalformedError):
        read_orientation(jpeg_with_exif(tiff))


# --- duplicate Orientation entries ---------------------------------------------------------------


@ORDERS
def test_two_orientation_entries_in_ifd0_are_refused_with_their_own_reason(order: str) -> None:
    tiff = block(order, [orientation(order, 6), orientation(order, 3)])
    data = jpeg_with_exif(tiff)
    with pytest.raises(JpegExifError) as caught:
        read_orientation(data)
    assert caught.value.reason == DUPLICATE_REASON
    with pytest.raises(JpegExifError) as caught:
        set_orientation(data, NEW_TAG)
    assert caught.value.reason == DUPLICATE_REASON


def test_a_photo_with_two_orientation_entries_is_skipped_for_that_reason(tmp_path) -> None:
    write_file(
        tmp_path, "a.jpg", jpeg_with_exif(block(">", [orientation(">", 6), orientation(">", 8)]))
    )
    row = decide_file(tmp_path, "a.jpg")
    assert (row.action, row.reason) == (Action.SKIP, DUPLICATE_REASON)
