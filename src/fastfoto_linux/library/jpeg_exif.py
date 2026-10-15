"""Change the EXIF Orientation of a JPEG without touching any other byte of the file.

The file is read as marker segments up to the start of the scan (SOS); everything from there on,
and every segment but the Exif APP1, is copied verbatim. When IFD0 already holds a SHORT
Orientation entry its two value bytes are patched in place, so the rest of the Exif block stays
byte-identical too. Only when the entry is missing (or oddly typed) is the Exif payload rebuilt
with Pillow's ``Image.Exif``, and a file without Exif gets a new APP1 after SOI/JFIF.
"""

import io
import struct
from dataclasses import dataclass

from PIL import Image

from fastfoto_linux.library.exif_errors import (
    ExifTooLargeError,
    JpegExifError,
    NotAJpegError,
)
from fastfoto_linux.library.tags import MAX_TAG, MIN_TAG, ORIENTATION_TAG

SOI = b"\xff\xd8"
MARKER_PREFIX = 0xFF
MARKER_SOS = 0xDA
MARKER_EOI = 0xD9
MARKER_APP0 = 0xE0
MARKER_APP1 = 0xE1
# Markers that stand alone, without a length: TEM, RST0-RST7 and a stray SOI (EOI is handled apart).
STANDALONE_MARKERS = frozenset({0x01, *range(0xD0, 0xD9)})
MARKER_SIZE = 2
LENGTH_SIZE = 2
SEGMENT_HEADER_SIZE = MARKER_SIZE + LENGTH_SIZE
MAX_SEGMENT_PAYLOAD = 65533  # a segment's length field counts itself and holds 16 bits
EXIF_HEADER = b"Exif\x00\x00"
JFIF_HEADER = b"JFIF\x00"
TIFF_BYTE_ORDERS = {b"II": "<", b"MM": ">"}
TIFF_MAGIC = 42
TIFF_HEADER_SIZE = 8
IFD_COUNT_SIZE = 2
IFD_ENTRY_SIZE = 12
ENTRY_VALUE_OFFSET = 8  # tag (2) + type (2) + count (4)
TYPE_SHORT = 3
TYPE_LONG = 4
SHORT_SIZE = 2


@dataclass(frozen=True)
class _Segment:
    marker: int
    start: int  # offset of the 0xFF marker byte
    end: int  # offset just past the segment's last byte

    @property
    def payload_start(self) -> int:
        return self.start + SEGMENT_HEADER_SIZE


@dataclass(frozen=True)
class _Entry:
    """The Orientation entry of IFD0: its value, and where to patch it if that is possible."""

    value: int | None
    patch_at: int | None  # offset of the two value bytes within the TIFF block
    byte_order: str


def _segments_before_scan(data: bytes) -> list[_Segment]:
    if data[: len(SOI)] != SOI:
        raise NotAJpegError("not a JPEG: it does not start with a start-of-image marker")
    segments: list[_Segment] = []
    position = len(SOI)
    while True:
        if position + MARKER_SIZE > len(data):
            raise NotAJpegError("the JPEG ends before its image data")
        if data[position] != MARKER_PREFIX:
            raise NotAJpegError(f"the JPEG has no segment marker at byte {position}")
        marker = data[position + 1]
        if marker == MARKER_SOS:
            return segments
        if marker == MARKER_EOI:
            raise NotAJpegError("the JPEG has no image data")
        if marker == MARKER_PREFIX or marker in STANDALONE_MARKERS:
            position += 1 if marker == MARKER_PREFIX else MARKER_SIZE
            continue
        segment = _read_segment(data, position)
        segments.append(segment)
        position = segment.end


def _read_segment(data: bytes, position: int) -> _Segment:
    if position + SEGMENT_HEADER_SIZE > len(data):
        raise NotAJpegError("the JPEG ends inside a segment header")
    (length,) = struct.unpack(">H", data[position + MARKER_SIZE : position + SEGMENT_HEADER_SIZE])
    end = position + MARKER_SIZE + length
    if length < LENGTH_SIZE or end > len(data):
        raise NotAJpegError(f"the JPEG has a segment at byte {position} that runs past its end")
    return _Segment(marker=data[position + 1], start=position, end=end)


def _find_exif(data: bytes, segments: list[_Segment]) -> _Segment | None:
    for segment in segments:
        if segment.marker == MARKER_APP1 and data.startswith(EXIF_HEADER, segment.payload_start):
            return segment
    return None


def _unpack(fmt: str, block: bytes, offset: int) -> tuple[int, ...]:
    size = struct.calcsize(fmt)
    if offset < 0 or offset + size > len(block):
        raise JpegExifError("the Exif data points outside itself")
    return struct.unpack_from(fmt, block, offset)


def _orientation_entry(tiff: bytes) -> _Entry:
    order = TIFF_BYTE_ORDERS.get(tiff[: len(b"II")])
    if order is None or len(tiff) < TIFF_HEADER_SIZE:
        raise JpegExifError("the Exif data has no valid TIFF header")
    if _unpack(f"{order}H", tiff, 2)[0] != TIFF_MAGIC:
        raise JpegExifError("the Exif data has no valid TIFF header")
    ifd = _unpack(f"{order}I", tiff, 4)[0]
    (count,) = _unpack(f"{order}H", tiff, ifd)
    for index in range(count):
        entry = ifd + IFD_COUNT_SIZE + index * IFD_ENTRY_SIZE
        tag, kind, number = _unpack(f"{order}HHI", tiff, entry)
        if tag == ORIENTATION_TAG:
            return _decode_entry(tiff, order, entry + ENTRY_VALUE_OFFSET, kind, number)
    return _Entry(value=None, patch_at=None, byte_order=order)


def _decode_entry(tiff: bytes, order: str, value_at: int, kind: int, number: int) -> _Entry:
    if number != 1 or kind not in (TYPE_SHORT, TYPE_LONG):
        raise JpegExifError("the Exif Orientation entry is not a single whole number")
    if kind == TYPE_SHORT:
        return _Entry(_unpack(f"{order}H", tiff, value_at)[0], value_at, order)
    return _Entry(_unpack(f"{order}I", tiff, value_at)[0], None, order)


def read_orientation(data: bytes) -> int | None:
    """The Orientation tag of the JPEG in ``data``; ``None`` when it has no Exif or no tag."""
    exif = _find_exif(data, _segments_before_scan(data))
    if exif is None:
        return None
    tiff = data[exif.payload_start + len(EXIF_HEADER) : exif.end]
    return _orientation_entry(tiff).value


def _segment_bytes(payload: bytes) -> bytes:
    if len(payload) > MAX_SEGMENT_PAYLOAD:
        raise ExifTooLargeError(
            f"the Exif data would be {len(payload)} bytes; a JPEG segment holds at most "
            f"{MAX_SEGMENT_PAYLOAD}"
        )
    length = struct.pack(">H", len(payload) + LENGTH_SIZE)
    return bytes([MARKER_PREFIX, MARKER_APP1]) + length + payload


def _rebuilt_payload(payload: bytes, tag: int) -> bytes:
    """``payload`` (with its ``Exif\\0\\0`` prefix) re-serialised with the Orientation set."""
    try:
        exif = Image.Exif()
        exif.load(payload)
        exif[ORIENTATION_TAG] = tag
        return exif.tobytes()
    except Exception as error:  # Pillow's parser meets untrusted bytes; report, never crash
        raise JpegExifError(f"the Exif data cannot be rebuilt ({type(error).__name__})") from error


def _new_payload(tag: int) -> bytes:
    exif = Image.Exif()
    exif[ORIENTATION_TAG] = tag
    return exif.tobytes()


def _insertion_point(data: bytes, segments: list[_Segment]) -> int:
    """Right after SOI, or after the JFIF segment when the file starts with one."""
    if segments:
        first = segments[0]
        if first.marker == MARKER_APP0 and data.startswith(JFIF_HEADER, first.payload_start):
            return first.end
    return len(SOI)


def _patched(data: bytes, at: int, byte_order: str, tag: int) -> bytes:
    return data[:at] + struct.pack(f"{byte_order}H", tag) + data[at + SHORT_SIZE :]


def _verified(result: bytes, tag: int) -> bytes:
    """``result`` once both our own reader and Pillow agree it now carries ``tag``."""
    try:
        with Image.open(io.BytesIO(result)) as image:
            pillow_tag = image.getexif().get(ORIENTATION_TAG)
    except Exception as error:  # an unreadable result must never be handed out
        name = type(error).__name__
        raise JpegExifError(f"the edited JPEG could not be re-read ({name})") from error
    if read_orientation(result) != tag or pillow_tag != tag:
        raise JpegExifError("the Orientation tag could not be confirmed after the change")
    return result


def set_orientation(data: bytes, tag: int) -> bytes:
    """``data`` with its Orientation tag set to ``tag`` (1-8) and every other byte unchanged.

    When the tag is missing, the Exif segment is rebuilt with it; a JPEG without Exif gets a new
    segment after SOI/JFIF. The result is re-read to confirm the tag.
    """
    if not MIN_TAG <= tag <= MAX_TAG:
        raise ValueError(f"the orientation must be between {MIN_TAG} and {MAX_TAG}, got {tag}")
    segments = _segments_before_scan(data)
    exif = _find_exif(data, segments)
    if exif is None:
        at = _insertion_point(data, segments)
        return _verified(data[:at] + _segment_bytes(_new_payload(tag)) + data[at:], tag)
    payload = data[exif.payload_start : exif.end]
    entry = _orientation_entry(payload[len(EXIF_HEADER) :])
    if entry.patch_at is not None:
        at = exif.payload_start + len(EXIF_HEADER) + entry.patch_at
        return _verified(_patched(data, at, entry.byte_order, tag), tag)
    rebuilt = _segment_bytes(_rebuilt_payload(payload, tag))
    return _verified(data[: exif.start] + rebuilt + data[exif.end :], tag)
