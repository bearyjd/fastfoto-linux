"""Change the EXIF Orientation of a JPEG without touching any other byte of the file.

The file is read as marker segments up to the start of the scan (SOS); everything from there on,
and every segment but the Exif APP1, is copied verbatim. Inside the Exif block ``tiff`` patches an
existing SHORT or LONG Orientation entry in place, or appends a copy of IFD0 that has one; no
other byte of the block moves. A file without Exif gets a new APP1 after SOI/JFIF.

Pillow never sees the file as it is: ``decoder_copy`` hands it a copy without the application
segments that a hostile file could use against it (a huge MPF table, say). The copy is made in
memory and only for decoding; the bytes that are written out are the file's own.
"""

import io
import re
import struct
from dataclasses import dataclass

from PIL import Image

from fastfoto_linux.library.exif_errors import (
    ExifTooLargeError,
    JpegExifError,
    NotAJpegError,
    TooManySegmentsError,
    XmpOrientationError,
)
from fastfoto_linux.library.tags import MAX_TAG, MIN_TAG, ORIENTATION_TAG
from fastfoto_linux.library.tiff import inspect_tiff, new_block, with_orientation

SOI = b"\xff\xd8"
MARKER_PREFIX = 0xFF
MARKER_SOS = 0xDA
MARKER_EOI = 0xD9
MARKER_APP0 = 0xE0
MARKER_APP1 = 0xE1
MARKER_APP14 = 0xEE
APP_MARKERS = range(0xE0, 0xF0)
# Start-of-frame markers: C0-CF except DHT (C4), JPG (C8) and DAC (CC), which are not frames.
FRAME_MARKERS = frozenset(set(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC})
FRAME_PAYLOAD_SIZE = 5  # precision (1), height (2), width (2)
# Markers that stand alone, without a length: TEM, RST0-RST7 and a stray SOI (EOI is handled apart).
STANDALONE_MARKERS = frozenset({0x01, *range(0xD0, 0xD9)})
MAX_SEGMENTS = 1024  # markers before the scan; a real photo has a few dozen at most
MARKER_SIZE = 2
LENGTH_SIZE = 2
SEGMENT_HEADER_SIZE = MARKER_SIZE + LENGTH_SIZE
MAX_SEGMENT_PAYLOAD = 65533  # a segment's length field counts itself and holds 16 bits
EXIF_HEADER = b"Exif\x00\x00"
JFIF_HEADER = b"JFIF\x00"
XMP_HEADER = b"http://ns.adobe.com/xap/1.0/\x00"
XMP_EXTENSION_HEADER = b"http://ns.adobe.com/xmp/extension/\x00"  # Extended XMP chunks
XMP_GUID_SIZE = 32  # names the packet a chunk belongs to
XMP_LENGTH_FIELD_SIZE = 4  # the packet's total length
XMP_OFFSET_FIELD_SIZE = 4  # where this chunk's bytes belong in the packet
XMP_TIFF_NAMESPACE = rb"http://ns\.adobe\.com/tiff/1\.0/"  # as a pattern
XMP_TIFF_PREFIX = b"tiff"  # the usual prefix: counted even where a packet forgets to bind it
ADOBE_HEADER = b"Adobe"  # tells the decoder how the colours are stored, so it is kept
MAX_ADOBE_PAYLOAD = 64
_FILL = re.compile(rb"\xff+")  # fill bytes may precede any marker
_QUOTE = rb"""(["'])"""
_XML_NAME = rb"[\w.-]+"
# ``xmlns:P="<tiff namespace>"``: P is a prefix for the tiff namespace, whatever its spelling.
_TIFF_BINDING = re.compile(
    rb"\sxmlns:(" + _XML_NAME + rb")\s*=\s*" + _QUOTE + XMP_TIFF_NAMESPACE + rb"\2"
)
_TIFF_DEFAULT = re.compile(rb"\sxmlns\s*=\s*" + _QUOTE + XMP_TIFF_NAMESPACE + rb"\1")
# ``<P:Orientation>`` or ``P:Orientation=`` (group 1 or 2 is P); not ``ex:Orientation`` for P = x.
_PREFIXED_ORIENTATION = re.compile(
    rb"<(" + _XML_NAME + rb"):Orientation(?=[\s/>])|\s(" + _XML_NAME + rb"):Orientation\s*="
)
_BARE_ORIENTATION = re.compile(rb"<Orientation(?=[\s/>])")


@dataclass(frozen=True)
class _Segment:
    marker: int
    start: int  # offset of the 0xFF marker byte
    end: int  # offset just past the segment's last byte

    @property
    def payload_start(self) -> int:
        return self.start + SEGMENT_HEADER_SIZE


@dataclass(frozen=True)
class Layout:
    """Where the segments before the scan are; parsed once and passed to the functions below."""

    segments: list[_Segment]
    scan_start: int  # offset of the SOS marker

    @classmethod
    def of(cls, data: bytes) -> "Layout":
        """The layout of ``data``; NotAJpegError (TooManySegmentsError) if it is not one we edit."""
        return _layout(data)


def _layout(data: bytes) -> Layout:
    if data[: len(SOI)] != SOI:
        raise NotAJpegError("not a JPEG: it does not start with a start-of-image marker")
    segments: list[_Segment] = []
    position = len(SOI)
    for _ in range(MAX_SEGMENTS):  # every marker counts, with or without a length
        if position + MARKER_SIZE > len(data):
            raise NotAJpegError("the JPEG ends before its image data")
        if data[position] != MARKER_PREFIX:
            raise NotAJpegError(f"the JPEG has no segment marker at byte {position}")
        run = _FILL.match(data, position)
        position = run.end() - 1 if run else position  # the last 0xFF belongs to the marker
        if position + MARKER_SIZE > len(data):
            raise NotAJpegError("the JPEG ends before its image data")
        marker = data[position + 1]
        if marker == MARKER_SOS:
            return Layout(segments, position)
        if marker == MARKER_EOI:
            raise NotAJpegError("the JPEG has no image data")
        if marker in STANDALONE_MARKERS:
            position += MARKER_SIZE
            continue
        segment = _read_segment(data, position)
        segments.append(segment)
        position = segment.end
    raise TooManySegmentsError(f"the JPEG has more than {MAX_SEGMENTS} markers before its image")


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


def read_orientation(data: bytes, layout: Layout | None = None) -> int | None:
    """The Orientation tag of the JPEG in ``data``; ``None`` when it has no Exif or no tag.

    The whole Exif block is checked first, so a malformed one is an error even when the tag is
    found early. ``layout`` is ``Layout.of(data)`` when the caller has it already.
    """
    layout = Layout.of(data) if layout is None else layout
    exif = _find_exif(data, layout.segments)
    if exif is None:
        return None
    entry = inspect_tiff(_tiff_block(data, exif)).orientation
    return None if entry is None else entry.value


def _names_orientation(data: bytes, start: int, end: int) -> bool:
    """Whether ``data[start:end]`` has an XMP Orientation in the tiff namespace.

    That is ``Orientation`` under a prefix bound to the namespace (``tiff`` and any other), or,
    where the namespace is the default one, an element without a prefix. The word elsewhere (a
    caption, a property of another namespace) is no orientation a viewer would prefer to the
    Exif one. One pass finds the bound prefixes and one the prefixes in use, so a hostile packet
    with thousands of them costs no more than a long one.
    """
    bound = {XMP_TIFF_PREFIX, *(m[1] for m in _TIFF_BINDING.finditer(data, start, end))}
    if any((m[1] or m[2]) in bound for m in _PREFIXED_ORIENTATION.finditer(data, start, end)):
        return True
    return (
        _TIFF_DEFAULT.search(data, start, end) is not None
        and _BARE_ORIENTATION.search(data, start, end) is not None
    )


def _extended_packets(data: bytes, segments: list[_Segment]) -> list[bytes]:
    """The Extended XMP packets, each put together from its chunks by their offsets.

    A chunk is the extension signature, the packet's GUID, its total length, the chunk's offset
    and then the packet's own bytes; only those bytes are joined, so a name cut in two by a chunk
    boundary is whole again.
    """
    packets: dict[bytes, list[tuple[int, bytes]]] = {}
    for segment in segments:
        if segment.marker != MARKER_APP1:
            continue
        if not data.startswith(XMP_EXTENSION_HEADER, segment.payload_start):
            continue
        guid_at = segment.payload_start + len(XMP_EXTENSION_HEADER)
        offset_at = guid_at + XMP_GUID_SIZE + XMP_LENGTH_FIELD_SIZE
        body_at = offset_at + XMP_OFFSET_FIELD_SIZE
        if body_at > segment.end:
            continue  # too short to hold the fields: it holds none of the packet
        (offset,) = struct.unpack_from(">I", data, offset_at)
        packets.setdefault(data[guid_at : guid_at + XMP_GUID_SIZE], []).append(
            (offset, data[body_at : segment.end])
        )
    return [b"".join(chunk for _, chunk in sorted(parts)) for parts in packets.values()]


def _xmp_has_orientation(data: bytes, segments: list[_Segment]) -> bool:
    """Whether an XMP packet, or an Extended XMP packet, names an Orientation."""
    if any(
        segment.marker == MARKER_APP1
        and data.startswith(XMP_HEADER, segment.payload_start)
        and _names_orientation(data, segment.payload_start, segment.end)
        for segment in segments
    ):
        return True
    packets = _extended_packets(data, segments)
    return any(_names_orientation(packet, 0, len(packet)) for packet in packets)


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
        layout = Layout.of(result)
        ours = read_orientation(result, layout)
    except JpegExifError as error:
        raise JpegExifError(
            f"the edited JPEG could not be re-read ({type(error).__name__})"
        ) from error
    try:
        with Image.open(io.BytesIO(decoder_copy(result, layout))) as image:
            pillow_tag = image.getexif().get(ORIENTATION_TAG)
    except Exception as error:  # an unreadable result must never be handed out
        name = type(error).__name__
        raise JpegExifError(f"the edited JPEG could not be re-read ({name})") from error
    if ours != tag or pillow_tag != tag:
        raise JpegExifError("the Orientation tag could not be confirmed after the change")
    return result


def set_orientation(data: bytes, tag: int, layout: Layout | None = None) -> bytes:
    """``data`` with its Orientation tag set to ``tag`` (1-8) and every other byte unchanged.

    A missing tag is added in an appended copy of IFD0; a JPEG without Exif gets a new segment
    after SOI/JFIF. A file whose XMP packet has an orientation of its own is refused: the two
    would disagree afterwards. The result is re-read to confirm the tag.
    """
    if not MIN_TAG <= tag <= MAX_TAG:
        raise ValueError(f"the orientation must be between {MIN_TAG} and {MAX_TAG}, got {tag}")
    segments = (Layout.of(data) if layout is None else layout).segments
    if _xmp_has_orientation(data, segments):
        raise XmpOrientationError("the XMP data has an Orientation of its own")
    exif = _find_exif(data, segments)
    if exif is None:
        edited = _splice(data, _insertion_point(data, segments), 0, EXIF_HEADER + new_block(tag))
    else:
        block = _tiff_block(data, exif)
        replacement = EXIF_HEADER + with_orientation(block, inspect_tiff(block), tag)
        edited = _splice(data, exif.start, exif.end - exif.start, replacement)
    return _verified(edited, tag)


def _splice(data: bytes, start: int, length: int, payload: bytes) -> bytes:
    """``data`` with ``length`` bytes at ``start`` replaced by an APP1 segment of ``payload``."""
    view = memoryview(data)
    return b"".join((view[:start], _segment_bytes(payload), view[start + length :]))


def pixel_count(data: bytes, layout: Layout | None = None) -> int:
    """Width times height as the JPEG's own frame header states them."""
    layout = Layout.of(data) if layout is None else layout
    for segment in layout.segments:
        if segment.marker in FRAME_MARKERS:
            if segment.end - segment.payload_start < FRAME_PAYLOAD_SIZE:
                raise NotAJpegError("the JPEG has a truncated frame header")
            height, width = struct.unpack_from(">HH", data, segment.payload_start + 1)
            return height * width
    raise NotAJpegError("the JPEG has no frame header")


def _keep_for_decoder(data: bytes, segment: _Segment, exif: _Segment | None) -> bool:
    if segment.marker not in APP_MARKERS:
        return True  # tables, the frame header and comments
    if segment.marker == MARKER_APP0:
        return True
    if segment is exif:
        return True
    adobe = segment.marker == MARKER_APP14 and data.startswith(ADOBE_HEADER, segment.payload_start)
    return adobe and segment.end - segment.payload_start <= MAX_ADOBE_PAYLOAD


def decoder_copy(data: bytes, layout: Layout | None = None) -> bytes:
    """A copy of the JPEG for Pillow: the same picture, with only the segments it needs.

    Kept: APP0 (JFIF), the Exif APP1 (after ``inspect_tiff`` has checked it), a short Adobe APP14
    (the colour transform) and every segment that is not an application segment. MPF, ICC, XMP,
    Photoshop and the other application segments are left out, so Pillow never parses them.
    """
    layout = Layout.of(data) if layout is None else layout
    exif = _find_exif(data, layout.segments)
    if exif is not None:
        inspect_tiff(_tiff_block(data, exif))
    view = memoryview(data)
    kept = [view[s.start : s.end] for s in layout.segments if _keep_for_decoder(data, s, exif)]
    return b"".join((SOI, *kept, view[layout.scan_start :]))
