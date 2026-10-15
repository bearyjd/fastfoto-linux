"""Change the EXIF Orientation of a JPEG without touching any other byte of the file.

The file is read as marker segments up to the start of the scan (SOS); everything from there on,
and every segment but the Exif APP1, is copied verbatim. Inside the Exif block ``tiff`` patches an
existing SHORT or LONG Orientation entry in place, or appends a copy of IFD0 that has one; no
other byte of the block moves. A file without Exif gets a new APP1 after SOI/JFIF.
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
from fastfoto_linux.library.tiff import inspect_tiff, new_block, with_orientation

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


@dataclass(frozen=True)
class _Segment:
    marker: int
    start: int  # offset of the 0xFF marker byte
    end: int  # offset just past the segment's last byte

    @property
    def payload_start(self) -> int:
        return self.start + SEGMENT_HEADER_SIZE


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


def _tiff_block(data: bytes, exif: _Segment) -> bytes:
    return data[exif.payload_start + len(EXIF_HEADER) : exif.end]


def read_orientation(data: bytes) -> int | None:
    """The Orientation tag of the JPEG in ``data``; ``None`` when it has no Exif or no tag.

    The whole Exif block is checked first, so a malformed one is an error even when the tag is
    found early.
    """
    exif = _find_exif(data, _segments_before_scan(data))
    if exif is None:
        return None
    entry = inspect_tiff(_tiff_block(data, exif)).orientation
    return None if entry is None else entry.value


def _segment_bytes(payload: bytes) -> bytes:
    if len(payload) > MAX_SEGMENT_PAYLOAD:
        raise ExifTooLargeError(
            f"the Exif data would be {len(payload)} bytes; a JPEG segment holds at most "
            f"{MAX_SEGMENT_PAYLOAD}"
        )
    length = struct.pack(">H", len(payload) + LENGTH_SIZE)
    return bytes([MARKER_PREFIX, MARKER_APP1]) + length + payload


def _insertion_point(data: bytes, segments: list[_Segment]) -> int:
    """Right after SOI, or after the JFIF segment when the file starts with one."""
    if segments:
        first = segments[0]
        if first.marker == MARKER_APP0 and data.startswith(JFIF_HEADER, first.payload_start):
            return first.end
    return len(SOI)


def _verified(result: bytes, tag: int) -> bytes:
    """``result`` once both our own reader and Pillow agree it now carries ``tag``.

    Our reader goes first: it checks the whole Exif block, so Pillow only ever sees a checked one.
    """
    try:
        ours = read_orientation(result)
    except JpegExifError as error:
        raise JpegExifError(
            f"the edited JPEG could not be re-read ({type(error).__name__})"
        ) from error
    try:
        with Image.open(io.BytesIO(result)) as image:
            pillow_tag = image.getexif().get(ORIENTATION_TAG)
    except Exception as error:  # an unreadable result must never be handed out
        name = type(error).__name__
        raise JpegExifError(f"the edited JPEG could not be re-read ({name})") from error
    if ours != tag or pillow_tag != tag:
        raise JpegExifError("the Orientation tag could not be confirmed after the change")
    return result


def set_orientation(data: bytes, tag: int) -> bytes:
    """``data`` with its Orientation tag set to ``tag`` (1-8) and every other byte unchanged.

    A missing tag is added in an appended copy of IFD0; a JPEG without Exif gets a new segment
    after SOI/JFIF. The result is re-read to confirm the tag.
    """
    if not MIN_TAG <= tag <= MAX_TAG:
        raise ValueError(f"the orientation must be between {MIN_TAG} and {MAX_TAG}, got {tag}")
    segments = _segments_before_scan(data)
    exif = _find_exif(data, segments)
    if exif is None:
        at = _insertion_point(data, segments)
        return _verified(data[:at] + _segment_bytes(EXIF_HEADER + new_block(tag)) + data[at:], tag)
    block = _tiff_block(data, exif)
    edited = with_orientation(block, inspect_tiff(block), tag)
    segment = _segment_bytes(EXIF_HEADER + edited)
    return _verified(data[: exif.start] + segment + data[exif.end :], tag)
