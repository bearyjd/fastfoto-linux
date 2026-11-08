"""Build PNG test files with a known orientation, and take chunk streams apart and back together.

Chunk-level helpers come from the photo editor's PNG helpers; this module adds the pieces the
library needs: a portrait stored sideways in a PNG, and a list view that keeps CRC mistakes.
"""

import io
import struct
import zlib

import numpy as np
from PIL import Image

from tests.face_images import load_astronaut
from tests.library.jpeg_helpers import exif_bytes, rotate_cw, stored_pixels
from tests.photo_edits.png_helpers import SIGNATURE, assemble, chunk, ihdr, split

__all__ = [
    "SIGNATURE",
    "assemble",
    "chunk",
    "corrupt_crc",
    "idat_bytes",
    "ihdr",
    "kinds",
    "make_png",
    "sideways_png",
    "split",
    "text_chunk",
    "with_after_idat",
    "with_before_idat",
    "xmp_packet",
]

XMP_KEYWORD = b"XML:com.adobe.xmp"
ORIENTATION_XMP = (
    b"<x:xmpmeta xmlns:x='adobe:ns:meta/'><rdf:RDF "
    b"xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>"
    b"<rdf:Description xmlns:tiff='http://ns.adobe.com/tiff/1.0/' tiff:Orientation='1'/>"
    b"</rdf:RDF></x:xmpmeta>"
)
PLAIN_XMP = ORIENTATION_XMP.replace(b"tiff:Orientation='1'", b"tiff:Make='Cam'")
OTHER_NAMESPACE_XMP = ORIENTATION_XMP.replace(
    b"xmlns:tiff='http://ns.adobe.com/tiff/1.0/' tiff:Orientation='1'",
    b"xmlns:ex='http://example.com/ns/' ex:Orientation='1'",
)


def make_png(pixels: np.ndarray, *, exif: bytes | None = None, mode: str | None = None) -> bytes:
    """A PNG of ``pixels`` (Pillow writes ``exif`` as an eXIf chunk before the image data)."""
    image = Image.fromarray(pixels)
    if mode is not None:
        image = image.convert(mode)
    buffer = io.BytesIO()
    image.save(buffer, "PNG", exif=exif or b"", compress_level=1)
    return buffer.getvalue()


def sideways_png(deviation: int, old_tag: int | None) -> bytes:
    """A PNG that currently *displays* the portrait turned ``deviation`` degrees clockwise."""
    displayed = rotate_cw(load_astronaut(), deviation)
    exif = exif_bytes(old_tag) if old_tag is not None else None
    return make_png(stored_pixels(displayed, old_tag), exif=exif)


def kinds(png: bytes) -> list[bytes]:
    return [kind for kind, _ in split(png)]


def idat_bytes(png: bytes) -> bytes:
    return b"".join(data for kind, data in split(png) if kind == b"IDAT")


def _insert(png: bytes, extra: list[tuple[bytes, bytes]], *, after: bool) -> bytes:
    chunks = split(png)
    at = next(i for i, (kind, _) in enumerate(chunks) if kind == b"IDAT")
    at = max(i for i, (kind, _) in enumerate(chunks) if kind == b"IDAT") + 1 if after else at
    return assemble([*chunks[:at], *extra, *chunks[at:]])


def with_before_idat(png: bytes, *extra: tuple[bytes, bytes]) -> bytes:
    return _insert(png, list(extra), after=False)


def with_after_idat(png: bytes, *extra: tuple[bytes, bytes]) -> bytes:
    return _insert(png, list(extra), after=True)


def xmp_packet(packet: bytes, carrier: str) -> tuple[bytes, bytes]:
    """The (type, data) chunk that carries ``packet`` as XMP in an iTXt, zTXt or tEXt chunk."""
    if carrier == "itxt":
        return b"iTXt", XMP_KEYWORD + b"\x00\x00\x00\x00\x00" + packet
    if carrier == "itxt-compressed":
        return b"iTXt", XMP_KEYWORD + b"\x00\x01\x00\x00\x00" + zlib.compress(packet)
    if carrier == "ztxt":
        return b"zTXt", XMP_KEYWORD + b"\x00\x00" + zlib.compress(packet)
    return b"tEXt", XMP_KEYWORD + b"\x00" + packet


def text_chunk(keyword: bytes, text: bytes) -> tuple[bytes, bytes]:
    return b"tEXt", keyword + b"\x00" + text


def corrupt_crc(png: bytes, kind: bytes) -> bytes:
    """``png`` with the CRC of its first ``kind`` chunk flipped."""
    pos = len(SIGNATURE)
    while pos < len(png):
        (length,) = struct.unpack(">I", png[pos : pos + 4])
        if png[pos + 4 : pos + 8] == kind:
            end = pos + 8 + length
            return png[:end] + bytes(b ^ 0xFF for b in png[end : end + 4]) + png[end + 4 :]
        pos += 12 + length
    raise AssertionError(f"no {kind!r} chunk")
