"""Small hand-built Exif blocks with the odd-but-harmless contents real cameras write."""

import struct

from tests.library.tiff_helpers import ASCII, LONG, SHORT, UNDEFINED

HEADER_SIZE = 8
ORIENTATION_TAG = 0x0112
EXIF_POINTER, GPS_POINTER = 0x8769, 0x8825
UNKNOWN_TYPE = 99
BEYOND_THE_BLOCK = 0x00FFFFFF


def entry(order: str, tag: int, kind: int, count: int, value: bytes | int) -> bytes:
    inline = struct.pack(order + "I", value) if isinstance(value, int) else value.ljust(4, b"\0")
    return struct.pack(order + "HHI", tag, kind, count) + inline


def orientation(order: str, value: int) -> bytes:
    return entry(order, ORIENTATION_TAG, SHORT, 1, struct.pack(order + "H", value))


def tail_at(entries: int) -> int:
    """Where bytes placed after IFD0 begin: 8 header, 2 count, 12 per entry, 4 next pointer."""
    return HEADER_SIZE + 2 + 12 * entries + 4


def block(order: str, entries: list[bytes], *, ifd0_next: int = 0, tail: bytes = b"") -> bytes:
    header = (b"II" if order == "<" else b"MM") + struct.pack(order + "HI", 42, HEADER_SIZE)
    ifd0 = struct.pack(order + "H", len(entries)) + b"".join(entries)
    return header + ifd0 + struct.pack(order + "I", ifd0_next) + tail


def ifd(order: str, entries: list[bytes], next_offset: int) -> bytes:
    body = struct.pack(order + "H", len(entries)) + b"".join(entries)
    return body + struct.pack(order + "I", next_offset)


def sub_ifd_entry(order: str) -> bytes:
    return entry(order, 0x9000, UNDEFINED, 4, b"0230")


__all__ = ["ASCII", "LONG", "SHORT", "UNDEFINED"]
