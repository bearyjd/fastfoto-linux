"""JPEG files with segments a hostile or odd camera could have written."""

import struct

from tests.library.jpeg_helpers import APP0, APP1, APP2, segment, sideways_jpeg

SOF_MARKERS = frozenset({0xC0, 0xC1, 0xC2})
RATIONAL_TYPE = 5
RATIONAL_SIZE = 8
XMP_START = b"http://ns.adobe.com/xap/1.0/\x00"


def insert_after_jfif(data: bytes, extra: bytes) -> bytes:
    """``data`` with the segment bytes ``extra`` right after SOI and the JFIF segment."""
    at = 2
    if data[3] == APP0:
        at += 2 + struct.unpack(">H", data[4:6])[0]
    return data[:at] + extra + data[at:]


def mpf_payload(entries: int, count: int) -> bytes:
    """An MPF APP2 payload whose IFD has ``entries`` entries that each claim ``count`` rationals.

    Every entry points at the same small data region, so the segment stays within 64 KiB while a
    reader that expands the values has millions of them to build.
    """
    header = b"II*\x00" + struct.pack("<I", 8)
    region = 8 + 2 + entries * 12 + 4
    ifd = b"".join(
        struct.pack("<HHII", 0x1000 + index, RATIONAL_TYPE, count, region)
        for index in range(entries)
    )
    return (
        b"MPF\x00"
        + header
        + struct.pack("<H", entries)
        + ifd
        + bytes(4)
        + bytes(RATIONAL_SIZE * count)
    )


def with_mpf_bomb(data: bytes, entries: int = 1000, count: int = 1200) -> tuple[bytes, bytes]:
    """``(file, the MPF payload)``."""
    payload = mpf_payload(entries, count)
    assert len(payload) <= 65533
    return insert_after_jfif(data, segment(APP2, payload)), payload


def with_xmp(data: bytes, packet: bytes) -> bytes:
    return insert_after_jfif(data, segment(APP1, XMP_START + packet))


def with_pixel_claim(data: bytes, width: int, height: int) -> bytes:
    """``data`` with the SOF header saying ``width`` x ``height`` (the scan data is unchanged)."""
    position = 2
    while True:
        marker = data[position + 1]
        length = struct.unpack(">H", data[position + 2 : position + 4])[0]
        if marker in SOF_MARKERS:
            sizes = struct.pack(">HH", height, width)
            return data[: position + 5] + sizes + data[position + 9 :]
        position += 2 + length


def sideways(deviation: int = 90) -> bytes:
    return sideways_jpeg(deviation, None)
