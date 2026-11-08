"""Change the EXIF Orientation of a PNG without touching any other byte of the file.

The file is read as chunks: signature, then length, type, data and CRC for each, up to IEND.
Every length and CRC is checked before anything is trusted, so a hostile length never sizes an
allocation. The single ``eXIf`` chunk is replaced by one holding the patched Exif block (``tiff``
patches an existing Orientation entry in place, or appends a copy of IFD0 that has one); a PNG
without ``eXIf`` gets a new chunk right before its image data. No other chunk is rewritten, so the
image data, the colour chunks and the text are exactly the file's own bytes.

This is a reader of its own, not ``photo_edits.png_guard``. That guard decides what the photo
editor can re-encode (8-bit RGB, sRGB only, no transparency) and speaks in editor messages; here
no pixel is re-encoded, so any valid colour type and depth is fine, and the answers are plan
reason codes. The chunk offsets the edit needs come from this module's scan.

Pillow never sees the file as it is: ``decoder_copy`` hands it the critical chunks and the
checked ``eXIf``, so text, ICC profile and XMP chunks (zlib bombs, oversized profiles) are never
parsed. Animated PNGs, PNGs with a chunk of unknown meaning that is marked critical, and PNGs
whose XMP or text chunks hold an orientation of their own are refused.
"""

import io
import struct
import zlib
from dataclasses import dataclass
from types import MappingProxyType

from PIL import Image

from fastfoto_linux.library.exif_errors import (
    ExifMalformedError,
    ExifTooLargeError,
    JpegExifError,
    NotAPngError,
    TooManySegmentsError,
    UnsupportedPngError,
    XmpOrientationError,
)
from fastfoto_linux.library.jpeg_exif import _names_orientation
from fastfoto_linux.library.tags import MAX_TAG, MIN_TAG, ORIENTATION_TAG
from fastfoto_linux.library.tiff import inspect_tiff, new_block, with_orientation

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
LENGTH_SIZE = 4
TYPE_SIZE = 4
CRC_SIZE = 4
HEADER_SIZE = LENGTH_SIZE + TYPE_SIZE
CHUNK_OVERHEAD = HEADER_SIZE + CRC_SIZE
MAX_CHUNK_LENGTH = 0x7FFFFFFF  # the PNG limit: lengths are 31 bits
MAX_DIMENSION = 0x7FFFFFFF
IHDR_LENGTH = 13
MAX_CHUNKS = 4096  # chunks other than image data; a real photo has a few dozen at most
MAX_TOTAL_CHUNKS = 131_072  # image data comes in chunks of 8 KiB and up; this bounds the scan
MAX_EXIF_CHUNK = 65_533  # what a JPEG Exif segment holds, and what the photo editor accepts
MAX_XMP_BYTES = 4 * 1024 * 1024  # an XMP packet is checked for an orientation up to this size
MAX_KEYWORD = 79  # PNG keywords are 1-79 bytes
CRITICAL_BIT = 0x20  # clear in the first letter of a critical chunk's type
IHDR, PLTE, IDAT, IEND = b"IHDR", b"PLTE", b"IDAT", b"IEND"
EXIF, ACTL = b"eXIf", b"acTL"
TEXT_KINDS = frozenset({b"tEXt", b"zTXt", b"iTXt"})
XMP_KEYWORD = b"XML:com.adobe.xmp"
# ImageMagick keeps an Exif copy in a text chunk; Pillow (and so some viewers) read it.
LEGACY_EXIF_KEYWORDS = frozenset({b"raw profile type exif", b"raw profile type app1"})
MIN_BITS_PER_PIXEL = 24  # Pillow converts every image to 8-bit RGB for the detector
# Colour type -> (channels, allowed bit depths).
COLOUR_TYPES = MappingProxyType(
    {
        0: (1, (1, 2, 4, 8, 16)),
        2: (3, (8, 16)),
        3: (1, (1, 2, 4, 8)),
        4: (2, (8, 16)),
        6: (4, (8, 16)),
    }
)
ITXT_COMPRESSED = 1
ZLIB_METHOD = 0


@dataclass(frozen=True)
class _Chunk:
    kind: bytes
    start: int  # offset of the length field
    end: int  # offset just past the CRC

    @property
    def data_start(self) -> int:
        return self.start + HEADER_SIZE

    @property
    def data_end(self) -> int:
        return self.end - CRC_SIZE

    @property
    def length(self) -> int:
        return self.data_end - self.data_start


@dataclass(frozen=True)
class Layout:
    """Where the chunks are; parsed once and passed to the functions below.

    ``chunks`` holds every chunk but image data, in order; the image data is one run of
    consecutive IDAT chunks, ``idat_start`` to ``idat_end``.
    """

    chunks: tuple[_Chunk, ...]
    idat_start: int
    idat_end: int
    width: int
    height: int
    bits_per_pixel: int

    @classmethod
    def of(cls, data: bytes) -> "Layout":
        """The layout of ``data``; NotAPngError (or a subclass of JpegExifError) if unsafe."""
        return _layout(data)

    @property
    def exif(self) -> _Chunk | None:
        return next((chunk for chunk in self.chunks if chunk.kind == EXIF), None)


def _read_chunk(data: bytes, position: int) -> _Chunk:
    """The chunk at ``position``, its length, type and CRC all checked against ``data``."""
    if position + HEADER_SIZE > len(data):
        raise NotAPngError("the PNG ends before its last chunk")
    (length,) = struct.unpack_from(">I", data, position)
    end = position + CHUNK_OVERHEAD + length
    if length > MAX_CHUNK_LENGTH or end > len(data):
        raise NotAPngError(f"the PNG has a chunk at byte {position} that runs past its end")
    kind = data[position + LENGTH_SIZE : position + HEADER_SIZE]
    if not kind.isalpha():
        raise NotAPngError(f"the PNG has a chunk at byte {position} with an invalid type")
    (stored,) = struct.unpack_from(">I", data, end - CRC_SIZE)
    if zlib.crc32(memoryview(data)[position + LENGTH_SIZE : end - CRC_SIZE]) != stored:
        raise NotAPngError(f"the PNG has a chunk at byte {position} with a wrong checksum")
    return _Chunk(kind, position, end)


def _admit(chunk: _Chunk, chunks: list[_Chunk], idat_seen: bool) -> None:
    """Refuse a non-image-data ``chunk`` that does not belong after ``chunks``."""
    if not chunks:
        if chunk.kind != IHDR or chunk.length != IHDR_LENGTH:
            raise NotAPngError("the PNG does not start with a valid header chunk")
        return
    if chunk.kind == IHDR:
        raise NotAPngError("the PNG has a second header chunk")
    if len(chunks) >= MAX_CHUNKS:
        raise TooManySegmentsError(f"the PNG has more than {MAX_CHUNKS} chunks besides its image")
    if chunk.kind == ACTL:
        raise UnsupportedPngError("the PNG is animated")
    critical = not chunk.kind[0] & CRITICAL_BIT
    if critical and chunk.kind not in (PLTE, IEND):
        raise UnsupportedPngError("the PNG has a critical chunk of an unknown kind")
    if chunk.kind == PLTE and (idat_seen or any(c.kind == PLTE for c in chunks)):
        raise NotAPngError("the PNG has a misplaced or repeated palette")
    if chunk.kind == IEND and chunk.length:
        raise NotAPngError("the PNG has an end chunk with data in it")
    if chunk.kind == EXIF:
        _admit_exif(chunk, chunks, idat_seen)


def _admit_exif(chunk: _Chunk, chunks: list[_Chunk], idat_seen: bool) -> None:
    if idat_seen or any(c.kind == EXIF for c in chunks):
        raise ExifMalformedError("the PNG has more than one Exif chunk, or one after the image")
    if chunk.length > MAX_EXIF_CHUNK:
        raise ExifTooLargeError(
            f"the Exif chunk is {chunk.length} bytes; at most {MAX_EXIF_CHUNK} are handled"
        )


def _parse_header(data: bytes, chunk: _Chunk) -> tuple[int, int, int]:
    """``(width, height, bits per pixel)`` from the header chunk; NotAPngError if invalid."""
    width, height, depth, colour, compression, filtering, interlace = struct.unpack_from(
        ">IIBBBBB", data, chunk.data_start
    )
    channels, depths = COLOUR_TYPES.get(colour, (0, ()))
    valid = 0 < width <= MAX_DIMENSION and 0 < height <= MAX_DIMENSION
    if not (
        valid and depth in depths and not compression and not filtering and interlace in (0, 1)
    ):
        raise NotAPngError("the PNG has an invalid header")
    return width, height, depth * channels


def _layout(data: bytes) -> Layout:
    if not data.startswith(PNG_SIGNATURE):
        raise NotAPngError("not a PNG: it does not start with the PNG signature")
    chunks: list[_Chunk] = []
    idat: tuple[int, int] | None = None
    position = len(PNG_SIGNATURE)
    for _ in range(MAX_TOTAL_CHUNKS):
        chunk = _read_chunk(data, position)
        position = chunk.end
        if chunk.kind == IDAT:
            if not chunks or (idat is not None and chunk.start != idat[1]):
                raise NotAPngError("the PNG's image data is not one run of chunks")
            idat = (chunk.start if idat is None else idat[0], chunk.end)
            continue
        _admit(chunk, chunks, idat is not None)
        chunks.append(chunk)
        if chunk.kind == IEND:
            break
    else:
        raise TooManySegmentsError("the PNG has too many chunks before its end")
    if idat is None or position != len(data):
        raise NotAPngError("the PNG has no image data, or has bytes after its end chunk")
    return Layout(tuple(chunks), idat[0], idat[1], *_parse_header(data, chunks[0]))


def _tiff_block(data: bytes, exif: _Chunk) -> bytes:
    return data[exif.data_start : exif.data_end]


def read_orientation(data: bytes, layout: Layout | None = None) -> int | None:
    """The Orientation tag of the PNG in ``data``; ``None`` when it has no Exif or no tag.

    The whole Exif block is checked first, so a malformed one is an error even when the tag is
    found early. ``layout`` is ``Layout.of(data)`` when the caller has it already.
    """
    layout = Layout.of(data) if layout is None else layout
    exif = layout.exif
    if exif is None:
        return None
    entry = inspect_tiff(_tiff_block(data, exif)).orientation
    return None if entry is None else entry.value


def pixel_count(data: bytes, layout: Layout | None = None) -> int:
    """The header's width times height, scaled up for pixels wider than 8-bit RGB.

    16-bit RGBA, say, takes 2.67 times the memory of RGB and counts that many times as many
    pixels, so one limit bounds the decoder's memory whatever the colour type.
    """
    layout = Layout.of(data) if layout is None else layout
    bits = max(layout.bits_per_pixel, MIN_BITS_PER_PIXEL)
    return -(-layout.width * layout.height * bits // MIN_BITS_PER_PIXEL)


def _inflate(compressed: bytes) -> bytes:
    """``compressed`` unpacked, up to ``MAX_XMP_BYTES``; XmpOrientationError if it is more."""
    unpacker = zlib.decompressobj()
    try:
        packet = unpacker.decompress(compressed, MAX_XMP_BYTES + 1)
    except zlib.error as error:
        raise XmpOrientationError("the XMP data could not be unpacked to be checked") from error
    if len(packet) > MAX_XMP_BYTES or not unpacker.eof:
        raise XmpOrientationError("the XMP data is too large or cut short to be checked")
    return packet


def _after_nul(data: bytes, start: int, end: int) -> int:
    """The offset just past the first NUL in ``data[start:end]``; XmpOrientationError if none."""
    found = data.find(b"\x00", start, end)
    if found < 0:
        raise XmpOrientationError("the XMP chunk is cut short")
    return found + 1


def _xmp_text(data: bytes, chunk: _Chunk, text_at: int) -> bytes:
    """The XMP packet of a tEXt, zTXt or iTXt chunk whose text part starts at ``text_at``."""
    end = chunk.data_end
    if chunk.kind == b"tEXt":
        packet = data[text_at:end]
        compressed = False
    elif chunk.kind == b"zTXt":
        if text_at >= end or data[text_at] != ZLIB_METHOD:
            raise XmpOrientationError("the XMP chunk uses an unknown compression")
        packet, compressed = data[text_at + 1 : end], True
    else:
        if text_at + 2 > end or data[text_at + 1] != ZLIB_METHOD:
            raise XmpOrientationError("the XMP chunk is cut short or uses an unknown compression")
        flag = data[text_at]
        language_end = _after_nul(data, text_at + 2, end)
        packet = data[_after_nul(data, language_end, end) : end]
        compressed = flag == ITXT_COMPRESSED
        if flag not in (0, ITXT_COMPRESSED):
            raise XmpOrientationError("the XMP chunk has an invalid compression flag")
    if compressed:
        return _inflate(packet)
    if len(packet) > MAX_XMP_BYTES:
        raise XmpOrientationError("the XMP data is too large to be checked")
    return packet


def _keyword(data: bytes, chunk: _Chunk) -> tuple[bytes, int] | None:
    """The keyword of a text chunk and the offset after its NUL; ``None`` if it has no valid one."""
    limit = min(chunk.data_end, chunk.data_start + MAX_KEYWORD + 1)
    nul = data.find(b"\x00", chunk.data_start, limit)
    return None if nul < 0 else (data[chunk.data_start : nul], nul + 1)


def _refuse_competing_orientations(data: bytes, layout: Layout) -> None:
    """Refuse a PNG whose XMP, or a text copy of Exif, has an orientation of its own: after the
    edit that and the eXIf one would disagree, and a viewer may obey the wrong one."""
    for chunk in layout.chunks:
        found = _keyword(data, chunk) if chunk.kind in TEXT_KINDS else None
        if found is None:
            continue
        keyword, text_at = found
        if keyword.lower() in LEGACY_EXIF_KEYWORDS:
            raise UnsupportedPngError("the PNG holds a text copy of its Exif data")
        if keyword == XMP_KEYWORD:
            packet = _xmp_text(data, chunk, text_at)
            if _names_orientation(packet, 0, len(packet)):
                raise XmpOrientationError("the XMP data has an Orientation of its own")


def _chunk_bytes(kind: bytes, payload: bytes) -> bytes:
    return b"".join(
        (
            struct.pack(">I", len(payload)),
            kind,
            payload,
            struct.pack(">I", zlib.crc32(kind + payload)),
        )
    )


def _splice(data: bytes, start: int, length: int, payload: bytes) -> bytes:
    """``data`` with ``length`` bytes at ``start`` replaced by an eXIf chunk of ``payload``."""
    if len(payload) > MAX_EXIF_CHUNK:
        raise ExifTooLargeError(
            f"the Exif data would be {len(payload)} bytes; at most {MAX_EXIF_CHUNK} are handled"
        )
    view = memoryview(data)
    return b"".join((view[:start], _chunk_bytes(EXIF, payload), view[start + length :]))


def _verified(result: bytes, tag: int) -> bytes:
    """``result`` once both our own reader and Pillow agree it now carries ``tag``.

    Our reader goes first: it checks every chunk and the whole Exif block, so Pillow only ever
    sees a checked one, and only the chunks ``decoder_copy`` keeps.
    """
    try:
        layout = Layout.of(result)
        ours = read_orientation(result, layout)
    except JpegExifError as error:
        raise JpegExifError(
            f"the edited PNG could not be re-read ({type(error).__name__})"
        ) from error
    try:
        with Image.open(io.BytesIO(decoder_copy(result, layout))) as image:
            pillow_tag = image.getexif().get(ORIENTATION_TAG)
    except Exception as error:  # an unreadable result must never be handed out
        name = type(error).__name__
        raise JpegExifError(f"the edited PNG could not be re-read ({name})") from error
    if ours != tag or pillow_tag != tag:
        raise JpegExifError("the Orientation tag could not be confirmed after the change")
    return result


def set_orientation(data: bytes, tag: int, layout: Layout | None = None) -> bytes:
    """``data`` with its Orientation tag set to ``tag`` (1-8) and every other byte unchanged.

    A missing tag is added in an appended copy of IFD0; a PNG without Exif gets a new eXIf chunk
    before its image data. A file whose XMP packet (or text copy of Exif) has an orientation of
    its own is refused. The result is re-read to confirm the tag.
    """
    if not MIN_TAG <= tag <= MAX_TAG:
        raise ValueError(f"the orientation must be between {MIN_TAG} and {MAX_TAG}, got {tag}")
    layout = Layout.of(data) if layout is None else layout
    _refuse_competing_orientations(data, layout)
    exif = layout.exif
    if exif is None:
        edited = _splice(data, layout.idat_start, 0, new_block(tag))
    else:
        block = _tiff_block(data, exif)
        replacement = with_orientation(block, inspect_tiff(block), tag)
        edited = _splice(data, exif.start, exif.end - exif.start, replacement)
    return _verified(edited, tag)


def decoder_copy(data: bytes, layout: Layout | None = None) -> bytes:
    """A copy of the PNG for Pillow: the same picture, with only the chunks it needs.

    Kept: the header, the palette, the image data, the end chunk and the Exif chunk (after
    ``inspect_tiff`` has checked it). Text, ICC, XMP, colour and every other ancillary chunk are
    left out, so Pillow never parses them (and never inflates a zlib bomb in them).
    """
    layout = Layout.of(data) if layout is None else layout
    exif = layout.exif
    if exif is not None:
        inspect_tiff(_tiff_block(data, exif))
    view = memoryview(data)
    head = [view[c.start : c.end] for c in layout.chunks if c.kind in (IHDR, PLTE, EXIF)]
    last = layout.chunks[-1]
    return b"".join(
        (
            PNG_SIGNATURE,
            *head,
            view[layout.idat_start : layout.idat_end],
            view[last.start : last.end],
        )
    )
