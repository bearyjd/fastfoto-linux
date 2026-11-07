"""Refuse unsafe PNG masters from raw bytes, before Pillow allocates or decodes anything."""

import struct
import zlib
from dataclasses import dataclass

from fastfoto_linux.photo_edits.model import MAX_SOURCE_PIXELS, PhotoEditError

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_CHUNKS = 4096
MAX_METADATA_CHUNK = 65_533
# The XMP packet itself: a JPEG APP1 spends 29 bytes on its namespace prefix, a PNG iTXt 22 on
# its header, so this packet fits either container and a saved edit always reopens.
JPEG_XMP_PREFIX = 29
MAX_XMP_PACKET = MAX_METADATA_CHUNK - JPEG_XMP_PREFIX
MAX_CHUNK_LENGTH = 0x7FFFFFFF
IHDR_LENGTH = 13
XMP_KEYWORD = b"XML:com.adobe.xmp\x00"
BAD_PNG = "the retained source is not a supported JPEG or PNG"
BAD_FORMAT = "photo edits support only 8-bit RGB PNG originals"
ANIMATED = "animated PNG originals are not supported"
TOO_MANY_PIXELS = "the PNG original has too many pixels"
BAD_METADATA = "the PNG original has duplicate, misplaced or oversized metadata"
UNKEPT_COLOUR = "the PNG original uses transparency or colour settings the editor cannot keep"
SRGB_GAMMA = 45455
GAMMA_LENGTH = 4
REFUSED_KINDS = frozenset({b"tRNS", b"cHRM", b"cICP", b"mDCv", b"cLLi"})
TOO_MANY_CHUNKS = "the PNG original has too many chunks"


@dataclass
class _Scan:
    """Mutable only inside one bounded scan; never escapes this module."""

    exif_chunks: int = 0
    xmp_chunks: int = 0
    seen_idat: bool = False
    seen_iend: bool = False
    iccp_chunks: int = 0
    phys_chunks: int = 0


def _read_header(data: bytes, pos: int) -> tuple[bytes, int, int]:
    """Type, data start and data length of the chunk at ``pos``, bounds-checked with its CRC."""
    if pos + 8 > len(data):
        raise PhotoEditError(BAD_PNG)
    (length,) = struct.unpack_from(">I", data, pos)
    if length > MAX_CHUNK_LENGTH or pos + 12 + length > len(data):
        raise PhotoEditError(BAD_PNG)
    return data[pos + 4 : pos + 8], pos + 8, length


def _check_crc(data: bytes, start: int, length: int) -> None:
    (stored,) = struct.unpack_from(">I", data, start + length)
    if zlib.crc32(data[start - 4 : start + length]) != stored:
        raise PhotoEditError(BAD_PNG)


def _check_ihdr(data: bytes) -> int:
    kind, start, length = _read_header(data, len(PNG_SIGNATURE))
    if kind != b"IHDR" or length != IHDR_LENGTH:
        raise PhotoEditError(BAD_PNG)
    _check_crc(data, start, length)
    width, height, depth, colour, compression, filtering, interlace = struct.unpack_from(
        ">IIBBBBB", data, start
    )
    if width == 0 or height == 0 or compression or filtering or interlace not in (0, 1):
        raise PhotoEditError(BAD_PNG)
    if width * height > MAX_SOURCE_PIXELS:
        raise PhotoEditError(TOO_MANY_PIXELS)
    if (depth, colour) != (8, 2):
        raise PhotoEditError(BAD_FORMAT)
    return start + length + 4


def _srgb_gamma(data: bytes, start: int, length: int) -> bool:
    return length == GAMMA_LENGTH and struct.unpack_from(">I", data, start)[0] == SRGB_GAMMA


def _count_once(kind: bytes, scan: _Scan) -> None:
    if kind == b"iCCP":
        scan.iccp_chunks += 1
    else:
        scan.phys_chunks += 1
    if scan.iccp_chunks > 1 or scan.phys_chunks > 1:
        raise PhotoEditError(BAD_METADATA)


def _check_chunk(kind: bytes, data: bytes, start: int, length: int, scan: _Scan) -> None:
    if kind == b"acTL":
        raise PhotoEditError(ANIMATED)
    if kind == b"IHDR":
        raise PhotoEditError(BAD_PNG)
    if kind in REFUSED_KINDS or (kind == b"gAMA" and not _srgb_gamma(data, start, length)):
        raise PhotoEditError(UNKEPT_COLOUR)
    if kind in (b"iCCP", b"pHYs"):
        _count_once(kind, scan)
    if kind == b"IDAT":
        scan.seen_idat = True
    elif kind == b"IEND":
        scan.seen_iend = True
    elif kind == b"eXIf":
        scan.exif_chunks += 1
        if scan.exif_chunks > 1 or scan.seen_idat or length > MAX_METADATA_CHUNK:
            raise PhotoEditError(BAD_METADATA)
    elif kind == b"iTXt" and data.startswith(XMP_KEYWORD, start):
        scan.xmp_chunks += 1
        if scan.xmp_chunks > 1 or length > MAX_METADATA_CHUNK:
            raise PhotoEditError(BAD_METADATA)


def check_png(data: bytes) -> None:
    """Raise PhotoEditError unless ``data`` is a bounded, static, 8-bit RGB PNG stream."""
    if not data.startswith(PNG_SIGNATURE):
        raise PhotoEditError(BAD_PNG)
    pos = _check_ihdr(data)
    scan = _Scan()
    for _ in range(MAX_CHUNKS):
        if scan.seen_iend or pos >= len(data):
            break
        kind, start, length = _read_header(data, pos)
        _check_crc(data, start, length)
        _check_chunk(kind, data, start, length, scan)
        pos = start + length + 4
    else:
        if not scan.seen_iend:
            raise PhotoEditError(TOO_MANY_CHUNKS)
    if not (scan.seen_idat and scan.seen_iend):
        raise PhotoEditError(BAD_PNG)
