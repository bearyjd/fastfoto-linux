"""Small JPEGs with hostile segments, built in memory."""

import io
import struct

import numpy as np
from PIL import Image

APP1 = 0xE1
APP2 = 0xE2
EXIF_HEADER = b"Exif\x00\x00"
XMP_HEADER = b"http://ns.adobe.com/xap/1.0/\x00"
ICC_HEADER = b"ICC_PROFILE\x00\x01\x01"
MAX_PAYLOAD = 65533
SIZE = 16
DPI = 300


def plain_jpeg() -> bytes:
    pixels = (np.arange(SIZE * SIZE * 3, dtype=np.uint8) * 5).reshape(SIZE, SIZE, 3)
    buffer = io.BytesIO()
    Image.fromarray(pixels).save(buffer, "JPEG", quality=90, dpi=(DPI, DPI))
    return buffer.getvalue()


def segment(marker: int, payload: bytes) -> bytes:
    """A marker segment; the payload is cut to what a segment can hold."""
    payload = payload[:MAX_PAYLOAD]
    return bytes([0xFF, marker]) + struct.pack(">H", len(payload) + 2) + payload


def with_segments(jpeg: bytes, *segments: bytes) -> bytes:
    """``jpeg`` with ``segments`` placed right after the start-of-image marker."""
    return jpeg[:2] + b"".join(segments) + jpeg[2:]


def with_size(jpeg: bytes, width: int, height: int) -> bytes:
    """``jpeg`` whose frame header claims another size (the entropy data is left as it is)."""
    marker = jpeg.index(b"\xff\xc0")
    return jpeg[: marker + 5] + struct.pack(">HH", height, width) + jpeg[marker + 9 :]
