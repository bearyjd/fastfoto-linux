"""An IFD0 "next IFD" pointer that points nowhere must not start pointing somewhere after an edit.

The edit appends a copy of IFD0 to the end of the Exif block. A pointer to IFD1 that lay past the
old end (or inside the header) would then point into the appended bytes, and be read as an IFD1
that is not one. Such a pointer means "no IFD1": the copy gets zero. A valid pointer is kept.
"""

import struct
from collections.abc import Callable
from pathlib import Path

import pytest

from fastfoto_linux.library.decide import decide_file
from fastfoto_linux.library.jpeg_exif import read_orientation, set_orientation
from fastfoto_linux.library.plan import Action
from tests.face_images import load_astronaut
from tests.library.jpeg_helpers import rotate_cw, write_file
from tests.library.tiff_edge_helpers import (
    ASCII,
    HEADER_SIZE,
    block,
    entry,
    ifd,
    orientation,
    tail_at,
)
from tests.library.tiff_helpers import exif_block, jpeg_with_exif

ORDERS = pytest.mark.parametrize("order", ["<", ">"])
RATIONAL = 5
NEW_TAG = 6
PAST_THE_END = range(61)  # k bytes after the last byte of the block
INSIDE_THE_HEADER = range(1, HEADER_SIZE)


def tiff_with_next(order: str, pointer: Callable[[int], int]) -> bytes:
    """IFD0 with three entries (no Orientation) and a rational value after it.

    ``pointer`` gives the next-IFD pointer from the length of the block.
    """
    entries = [
        entry(order, 0x010F, ASCII, 4, b"abc\0"),
        entry(order, 0x0131, ASCII, 4, b"xyz\0"),
        entry(order, 0x011A, RATIONAL, 1, tail_at(3)),
    ]
    tail = struct.pack(order + "II", 72, 1)
    length = len(block(order, entries, tail=tail))
    return block(order, entries, ifd0_next=pointer(length), tail=tail)


def next_pointer_of_ifd0(tiff: bytes, order: str) -> int:
    """The next-IFD pointer of the IFD0 the header points at, read without the code under test."""
    (ifd0,) = struct.unpack_from(order + "I", tiff, 4)
    (count,) = struct.unpack_from(order + "H", tiff, ifd0)
    return struct.unpack_from(order + "I", tiff, ifd0 + 2 + 12 * count)[0]


def problems(order: str, pointers: list[Callable[[int], int]]) -> list[tuple[int, str]]:
    found = []
    for index, pointer in enumerate(pointers):
        tiff = tiff_with_next(order, pointer)
        try:
            result = set_orientation(jpeg_with_exif(tiff), NEW_TAG)
        except ValueError as error:
            found.append((index, f"edit refused: {error}"))
            continue
        edited = exif_block(result)
        if read_orientation(result) != NEW_TAG:
            found.append((index, "the tag was not set"))
        elif next_pointer_of_ifd0(edited, order) != 0:
            found.append((index, "the pointer was carried over"))
        elif edited[:4] != tiff[:4] or edited[HEADER_SIZE : len(tiff)] != tiff[HEADER_SIZE:]:
            found.append((index, "an old byte moved"))
    return found


@ORDERS
def test_a_next_pointer_at_or_past_the_end_of_the_block_is_zero_in_the_appended_copy(
    order: str,
) -> None:
    pointers = [lambda length, k=k: length + k for k in PAST_THE_END]
    assert problems(order, pointers) == []


@ORDERS
def test_a_next_pointer_inside_the_header_is_zero_in_the_appended_copy(order: str) -> None:
    pointers = [lambda _length, k=k: k for k in INSIDE_THE_HEADER]
    assert problems(order, pointers) == []


@ORDERS
@pytest.mark.parametrize("beyond", [0, 2, 10, 30, 60])
def test_a_sideways_photo_with_such_a_pointer_is_rotated_not_skipped(
    tmp_path: Path, order: str, beyond: int
) -> None:
    tiff = tiff_with_next(order, lambda length: length + beyond)
    data = jpeg_with_exif(tiff, pixels=rotate_cw(load_astronaut(), 90))
    write_file(tmp_path, "a.jpg", data)
    row = decide_file(tmp_path, "a.jpg")
    assert (row.action, row.reason) == (Action.ROTATE, "faces-upright-after-turn")


@ORDERS
def test_a_valid_next_pointer_is_carried_over_so_ifd1_stays_reachable(order: str) -> None:
    entries = [entry(order, 0x010F, ASCII, 4, b"abc\0")]
    start = HEADER_SIZE + 2 + 12 * len(entries) + 4
    tiff = block(order, entries, ifd0_next=start, tail=ifd(order, [orientation(order, 1)], 0))
    result = set_orientation(jpeg_with_exif(tiff), NEW_TAG)
    assert next_pointer_of_ifd0(exif_block(result), order) == start
