"""Bounded reading of an Exif (TIFF) block, and the one edit this tool makes to it.

Exif comes from the file, so nothing in it is trusted. ``inspect_tiff`` walks every IFD it can
reach (IFD0, the Exif/GPS/Interoperability sub-IFDs and the next-IFD chain, each at most once)
and checks every entry against the block before anything else parses it: the type is known,
``count * size`` and the value offset stay inside the block, and the work stays proportional to
the block's size.

The edit never moves a byte. An existing SHORT or LONG Orientation entry is patched in place;
otherwise IFD0 is copied to the end of the block with one new 12-byte entry in tag order, and only
the header's pointer to IFD0 changes. The old IFD0 stays behind as unreferenced bytes, so IFD1
(thumbnail), MakerNote offsets and every value remain exactly as they were.
"""

import struct
from dataclasses import dataclass
from types import MappingProxyType

from fastfoto_linux.library.exif_errors import (
    ExifDuplicateOrientationError,
    ExifMalformedError,
    JpegExifError,
)
from fastfoto_linux.library.tags import ORIENTATION_TAG

TIFF_BYTE_ORDERS = MappingProxyType({b"II": "<", b"MM": ">"})
TIFF_MAGIC = 42
TIFF_HEADER_SIZE = 8
IFD_OFFSET_AT = 4  # the header's pointer to IFD0
IFD_COUNT_SIZE = 2
IFD_ENTRY_SIZE = 12
NEXT_IFD_SIZE = 4
ENTRY_VALUE_AT = 8  # tag (2) + type (2) + count (4)
INLINE_VALUE_SIZE = 4
TYPE_SHORT = 3
TYPE_LONG = 4
TYPE_IFD = 13
SHORT_SIZE = 2
LONG_SIZE = 4
UNKNOWN_TYPE_SIZE = 1  # a type this reader does not know is counted in bytes, still bounds-checked
# Bytes in one value of each TIFF type that classic TIFF and Exif use.
TYPE_SIZES = MappingProxyType(
    {
        1: 1,
        2: 1,
        3: SHORT_SIZE,
        4: LONG_SIZE,
        5: 8,
        6: 1,
        7: 1,
        8: 2,
        9: 4,
        10: 8,
        11: 4,
        12: 8,
        13: 4,
    }
)
# Entries that point at a further IFD: Exif, GPS and Interoperability.
SUB_IFD_TAGS = frozenset({0x8769, 0x8825, 0xA005})
POINTER_TYPES = (TYPE_LONG, TYPE_IFD)
SHORT_FORMAT, LONG_FORMAT = "H", "I"


@dataclass(frozen=True)
class OrientationEntry:
    """IFD0's Orientation entry: its value and the bytes of the value field to patch."""

    value: int
    value_at: int  # offset of the value field within the block
    width: int  # 2 for a SHORT, 4 for a LONG


@dataclass(frozen=True)
class TiffInfo:
    """What the edit needs to know about a block that passed every check."""

    byte_order: str
    ifd0_offset: int
    ifd0_count: int
    insert_index: int  # where a new Orientation entry goes to keep IFD0 in tag order
    orientation: OrientationEntry | None


class _Walk:
    """One validation: the block, the IFDs seen so far and how much work is left."""

    def __init__(self, block: bytes, order: str) -> None:
        self.block = block
        self.order = order
        self.visited: set[int] = set()
        self.entries_left = len(block) // IFD_ENTRY_SIZE
        self.value_bytes_left = len(block)

    def unpack(self, fmt: str, offset: int) -> tuple[int, ...]:
        size = struct.calcsize(fmt)
        if offset < 0 or offset + size > len(self.block):
            raise ExifMalformedError("the Exif data points outside itself")
        return struct.unpack_from(self.order + fmt, self.block, offset)

    def check_value(self, at: int, kind: int, number: int) -> None:
        total = TYPE_SIZES.get(kind, UNKNOWN_TYPE_SIZE) * number
        if total <= INLINE_VALUE_SIZE:
            return
        (offset,) = self.unpack(LONG_FORMAT, at + ENTRY_VALUE_AT)
        if offset < TIFF_HEADER_SIZE or offset + total > len(self.block):
            raise ExifMalformedError("the Exif data has a value that runs outside itself")
        self.value_bytes_left -= total
        if self.value_bytes_left < 0:
            raise ExifMalformedError("the Exif data holds more values than it has room for")


def _ifd_entries(walk: _Walk, offset: int) -> list[tuple[int, int, int, int]]:
    """``(tag, type, count, entry offset)`` of every entry of the IFD at ``offset``, all checked."""
    if offset in walk.visited:
        raise ExifMalformedError("the Exif data loops back to an IFD it already has")
    walk.visited.add(offset)
    if offset < TIFF_HEADER_SIZE:
        raise ExifMalformedError("the Exif data has an IFD inside its own header")
    (count,) = walk.unpack(SHORT_FORMAT, offset)
    end = offset + IFD_COUNT_SIZE + count * IFD_ENTRY_SIZE + NEXT_IFD_SIZE
    walk.entries_left -= count
    if end > len(walk.block) or walk.entries_left < 0:
        raise ExifMalformedError("the Exif data has an IFD with more entries than fit")
    entries = []
    for index in range(count):
        at = offset + IFD_COUNT_SIZE + index * IFD_ENTRY_SIZE
        tag, kind, number = walk.unpack("HHI", at)
        walk.check_value(at, kind, number)
        entries.append((tag, kind, number, at))
    return entries


def _header(block: bytes) -> tuple[str, int]:
    order = TIFF_BYTE_ORDERS.get(block[: len(b"II")])
    if order is None or len(block) < TIFF_HEADER_SIZE:
        raise ExifMalformedError("the Exif data has no valid TIFF header")
    (magic,) = struct.unpack_from(order + SHORT_FORMAT, block, len(b"II"))
    if magic != TIFF_MAGIC:
        raise ExifMalformedError("the Exif data has no valid TIFF header")
    return order, struct.unpack_from(order + LONG_FORMAT, block, IFD_OFFSET_AT)[0]


def _orientation(walk: _Walk, entries: list[tuple[int, int, int, int]]) -> OrientationEntry | None:
    found = [entry for entry in entries if entry[0] == ORIENTATION_TAG]
    if len(found) > 1:
        raise ExifDuplicateOrientationError("the Exif data has more than one Orientation entry")
    if not found:
        return None
    _, kind, number, at = found[0]
    if number != 1 or kind not in (TYPE_SHORT, TYPE_LONG):
        raise JpegExifError("the Exif Orientation entry is not a single whole number")
    fmt, width = (SHORT_FORMAT, SHORT_SIZE) if kind == TYPE_SHORT else (LONG_FORMAT, LONG_SIZE)
    (value,) = walk.unpack(fmt, at + ENTRY_VALUE_AT)
    return OrientationEntry(value, at + ENTRY_VALUE_AT, width)


def _sub_ifd_offsets(walk: _Walk, entries: list[tuple[int, int, int, int]]) -> list[int]:
    offsets = []
    for tag, kind, number, at in entries:
        if tag in SUB_IFD_TAGS:
            if kind not in POINTER_TYPES or number != 1:
                raise ExifMalformedError("the Exif data has a sub-IFD pointer of the wrong kind")
            target = walk.unpack(LONG_FORMAT, at + ENTRY_VALUE_AT)[0]
            if target:  # a pointer of zero says there is no such IFD
                offsets.append(target)
    return offsets


def _next_ifd(walk: _Walk, offset: int, entries: list[tuple[int, int, int, int]]) -> int | None:
    """The IFD that follows the one at ``offset`` (IFD1 after IFD0), or ``None`` if there is none.

    A pointer of zero, or one that points past the end of the block, means there is none; the
    pointer itself is carried over untouched by the edit.
    """
    following = walk.unpack(LONG_FORMAT, offset + IFD_COUNT_SIZE + len(entries) * IFD_ENTRY_SIZE)[0]
    return following if 0 < following < len(walk.block) else None


def _check_sub_ifds(walk: _Walk, entries: list[tuple[int, int, int, int]]) -> None:
    """Check the Exif, GPS and Interoperability IFDs below ``entries``; their next pointers are
    not followed, since nothing reads them."""
    pending = _sub_ifd_offsets(walk, entries)
    while pending:
        pending += _sub_ifd_offsets(walk, _ifd_entries(walk, pending.pop()))


def inspect_tiff(block: bytes) -> TiffInfo:
    """Check every IFD reachable in ``block`` and describe IFD0; ExifMalformedError if unsafe."""
    order, ifd0 = _header(block)
    walk = _Walk(block, order)
    entries = _ifd_entries(walk, ifd0)
    tags = [tag for tag, *_ in entries]
    insert = next((i for i, tag in enumerate(tags) if tag > ORIENTATION_TAG), len(tags))
    info = TiffInfo(order, ifd0, len(entries), insert, _orientation(walk, entries))
    _check_sub_ifds(walk, entries)
    following = _next_ifd(walk, ifd0, entries)
    if following is not None:
        _ifd_entries(walk, following)  # IFD1: its entries are checked, its successor is ignored
    return info


def _appended(block: bytes, info: TiffInfo, tag: int) -> bytes:
    """``block`` with a copy of IFD0 plus the new Orientation entry added at its end."""
    order = info.byte_order
    first = info.ifd0_offset + IFD_COUNT_SIZE
    split = first + info.insert_index * IFD_ENTRY_SIZE
    entries_end = first + info.ifd0_count * IFD_ENTRY_SIZE
    entry = struct.pack(f"{order}HHIHH", ORIENTATION_TAG, TYPE_SHORT, 1, tag, 0)
    copy = (
        struct.pack(f"{order}{SHORT_FORMAT}", info.ifd0_count + 1)
        + block[first:split]
        + entry
        + block[split:entries_end]
        + block[entries_end : entries_end + NEXT_IFD_SIZE]  # IFD1 stays reachable as it was
    )
    padding = bytes(len(block) % 2)  # the copy starts on an even offset
    start = len(block) + len(padding)
    repointed = struct.pack(f"{order}{LONG_FORMAT}", start)
    return block[:IFD_OFFSET_AT] + repointed + block[TIFF_HEADER_SIZE:] + padding + copy


def with_orientation(block: bytes, info: TiffInfo, tag: int) -> bytes:
    """``block`` showing ``tag`` as its Orientation, with every other byte where it was."""
    current = info.orientation
    if current is None:
        return _appended(block, info, tag)
    fmt = SHORT_FORMAT if current.width == SHORT_SIZE else LONG_FORMAT
    value = struct.pack(f"{info.byte_order}{fmt}", tag)
    return block[: current.value_at] + value + block[current.value_at + current.width :]


def new_block(tag: int) -> bytes:
    """A minimal big-endian TIFF block whose only entry is the Orientation ``tag``."""
    header = b"MM" + struct.pack(">HI", TIFF_MAGIC, TIFF_HEADER_SIZE)
    entry = struct.pack(">HHIHH", ORIENTATION_TAG, TYPE_SHORT, 1, tag, 0)
    return header + struct.pack(">H", 1) + entry + struct.pack(">I", 0)
