"""Hand-built TIFF/Exif blocks with awkward contents, and an independent reader for them.

The block holds what a naive rewrite would damage: an IFD1 with a thumbnail, a MakerNote with an
absolute offset inside it, a Latin-1 string, an unnormalised rational (600/2) and, optionally, an
Orientation entry typed SHORT or LONG. ``read_tags`` is deliberately a separate, tolerant reader
so the tests do not depend on the code they check.
"""

import struct
from dataclasses import dataclass

from tests.face_images import load_astronaut
from tests.library.jpeg_helpers import APP1, EXIF_HEADER, ORIENTATION, make_jpeg, segment

ASCII, SHORT, LONG, RATIONAL, UNDEFINED = 2, 3, 4, 5, 7
TYPE_SIZE = {1: 1, ASCII: 1, SHORT: 2, LONG: 4, RATIONAL: 8, UNDEFINED: 1}
IFD_ENTRY_SIZE = 12
HEADER_SIZE = 8
EXIF_IFD_POINTER = 0x8769
THUMBNAIL = b"\xff\xd8THUMB\xff\xd9"
LATIN1_TEXT = b"abc\xe9\x00"  # "abc" + e-acute in Latin-1, which Pillow would turn into "abc?"
UNNORMALISED = (600, 2)
MAKER_NOTE_TEXT = b"MAKERSTR\x00"
DATE_TEXT = b"2001:02:03 04:05:06\x00"

Tags = dict[tuple[str, int], tuple[int, int, bytes]]


@dataclass(frozen=True)
class TiffFixture:
    block: bytes
    where: dict[str, int]  # offset of each region ("ifd0", "ifd1", "maker", "thumb", ...)
    order: str
    entries_in_ifd0: int


def _pack_entry(order: str, tag: int, kind: int, count: int, value: bytes | int) -> bytes:
    inline = struct.pack(order + "I", value) if isinstance(value, int) else value.ljust(4, b"\0")
    return struct.pack(order + "HHI", tag, kind, count) + inline


def _assemble(
    order: str, orientation: tuple[int, int] | None, where: dict[str, int], odd: bool
) -> tuple[bytes, dict[str, int]]:
    """One layout pass; ``where`` holds the offsets found by the previous pass."""
    parts: list[tuple[str, bytes]] = []

    def u16(value: int) -> bytes:
        return struct.pack(order + "H", value)

    def u32(value: int) -> bytes:
        return struct.pack(order + "I", value)

    ifd0 = [
        _pack_entry(order, 0x010E, ASCII, len(LATIN1_TEXT), where["desc"]),
        _pack_entry(order, 0x011A, RATIONAL, 1, where["xres"]),
        _pack_entry(order, 0x0132, ASCII, len(DATE_TEXT), where["date"]),
        _pack_entry(order, EXIF_IFD_POINTER, LONG, 1, where["exif"]),
    ]
    if orientation is not None:
        kind, value = orientation
        packed = u16(value) if kind == SHORT else u32(value)
        ifd0.insert(1, _pack_entry(order, ORIENTATION, kind, 1, packed))
    maker = (
        b"MKNT" + u16(1) + _pack_entry(order, 1, ASCII, len(MAKER_NOTE_TEXT), where["maker"] + 22)
    )
    maker += u32(0) + MAKER_NOTE_TEXT
    exif = [
        _pack_entry(order, 0x9000, UNDEFINED, 4, b"0230"),
        _pack_entry(order, 0x927C, UNDEFINED, len(maker), where["maker"]),
    ]
    ifd1 = [
        _pack_entry(order, 0x0201, LONG, 1, where["thumb"]),
        _pack_entry(order, 0x0202, LONG, 1, len(THUMBNAIL)),
    ]

    def ifd(entries: list[bytes], next_offset: int) -> bytes:
        return u16(len(entries)) + b"".join(entries) + u32(next_offset)

    parts.append(("header", (b"MM" if order == ">" else b"II") + u16(42) + u32(HEADER_SIZE)))
    parts.append(("ifd0", ifd(ifd0, where["ifd1"])))
    parts.append(("desc", LATIN1_TEXT.ljust(6, b"\0")))
    parts.append(("xres", u32(UNNORMALISED[0]) + u32(UNNORMALISED[1])))
    parts.append(("date", DATE_TEXT))
    parts.append(("exif", ifd(exif, 0)))
    parts.append(("maker", maker.ljust(len(maker) + len(maker) % 2, b"\0")))
    parts.append(("ifd1", ifd(ifd1, 0)))
    parts.append(("thumb", THUMBNAIL))
    buffer, found = b"", {}
    for name, data in parts:
        found[name] = len(buffer)
        buffer += data
    if (len(buffer) % 2 == 1) != odd:
        buffer += b"\0"
    return buffer, found


def build_tiff(
    order: str = ">", orientation: tuple[int, int] | None = None, *, odd: bool = False
) -> TiffFixture:
    """The block; ``orientation`` is ``(SHORT or LONG, value)``, ``odd`` makes its length odd."""
    zeros = {name: 0 for name in ("desc", "xres", "date", "exif", "maker", "ifd1", "thumb")}
    _, where = _assemble(order, orientation, zeros, odd)
    block, again = _assemble(order, orientation, where, odd)
    assert again == where
    count = 4 + (orientation is not None)
    return TiffFixture(block, where, order, count)


def jpeg_with_exif(block: bytes, pixels=None) -> bytes:
    """A real JPEG whose Exif segment is ``block`` (after the ``Exif\\0\\0`` prefix)."""
    data = make_jpeg(pixels if pixels is not None else load_astronaut())
    jfif_end = 4 + struct.unpack(">H", data[4:6])[0]
    return data[:jfif_end] + segment(APP1, EXIF_HEADER + block) + data[jfif_end:]


def exif_block(jpeg: bytes) -> bytes:
    """The TIFF block of the first Exif segment of ``jpeg``."""
    at = jpeg.index(EXIF_HEADER)
    (length,) = struct.unpack(">H", jpeg[at - 2 : at])
    return jpeg[at + len(EXIF_HEADER) : at - 2 + length]


def read_tags(block: bytes) -> Tags:
    """Every tag of IFD0, IFD1 and the Exif sub-IFD as ``(type, count, raw value bytes)``."""
    order = ">" if block[:2] == b"MM" else "<"
    tags: Tags = {}

    def read_ifd(name: str, offset: int) -> int:
        (count,) = struct.unpack_from(order + "H", block, offset)
        for index in range(count):
            at = offset + 2 + index * IFD_ENTRY_SIZE
            tag, kind, number = struct.unpack_from(order + "HHI", block, at)
            size = TYPE_SIZE[kind] * number
            if size <= 4:
                raw = block[at + 8 : at + 8 + size]
            else:
                (value_at,) = struct.unpack_from(order + "I", block, at + 8)
                raw = block[value_at : value_at + size]
            tags[(name, tag)] = (kind, number, raw)
            if tag == EXIF_IFD_POINTER:
                (sub,) = struct.unpack_from(order + "I", block, at + 8)
                read_ifd("exif", sub)
        (following,) = struct.unpack_from(order + "I", block, offset + 2 + count * IFD_ENTRY_SIZE)
        return following

    (first,) = struct.unpack_from(order + "I", block, 4)
    second = read_ifd("ifd0", first)
    if second:
        read_ifd("ifd1", second)
    return tags
