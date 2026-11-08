"""Tiny in-memory PNG masters and hand-assembled chunk streams; no files, no scans."""

import io
import struct
import zlib
from datetime import datetime

import numpy as np
from PIL import Image

from fastfoto_linux.output.metadata import PhotoMetadata, build_exif, build_xmp
from fastfoto_linux.output.photo_encode import encode_photo
from fastfoto_linux.output.presets import ExportPreset

SIGNATURE = b"\x89PNG\r\n\x1a\n"
WIDTH = 8
HEIGHT = 6
NOW = datetime(2026, 1, 2, 3, 4, 5)
META = PhotoMetadata(scanned_at=NOW, written_at=NOW, album="Album", notes="A note & <more>")
XMP = build_xmp(META)


def pixels() -> np.ndarray:
    grid = np.arange(HEIGHT * WIDTH * 3, dtype=np.uint8) * 3
    return grid.reshape(HEIGHT, WIDTH, 3)


def master_png(dpi: int = 600) -> bytes:
    """What `--preset lossless` writes: pHYs dpi, eXIf and an iTXt XMP packet."""
    return encode_photo(
        pixels(),
        dpi=dpi,
        quality=95,
        preset=ExportPreset.LOSSLESS,
        exif=build_exif(META),
        xmp=XMP,
    )


def chunk(kind: bytes, data: bytes, *, crc: int | None = None) -> bytes:
    checksum = zlib.crc32(kind + data) if crc is None else crc
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)


def split(png: bytes) -> list[tuple[bytes, bytes]]:
    """(type, data) for every chunk of a well-formed PNG."""
    out, pos = [], len(SIGNATURE)
    while pos < len(png):
        (length,) = struct.unpack(">I", png[pos : pos + 4])
        out.append((png[pos + 4 : pos + 8], png[pos + 8 : pos + 8 + length]))
        pos += 12 + length
    return out


def assemble(chunks: list[tuple[bytes, bytes]]) -> bytes:
    return SIGNATURE + b"".join(chunk(kind, data) for kind, data in chunks)


def ihdr(width: int, height: int, depth: int = 8, colour: int = 2, interlace: int = 0) -> bytes:
    return struct.pack(">IIBBBBB", width, height, depth, colour, 0, 0, interlace)


def with_chunks(png: bytes, *, before_idat: tuple = (), after_idat: tuple = ()) -> bytes:
    """Insert extra (type, data) chunks around the first IDAT of a master."""
    chunks = split(png)
    at = next(i for i, (kind, _) in enumerate(chunks) if kind == b"IDAT")
    return assemble([*chunks[:at], *before_idat, chunks[at], *after_idat, *chunks[at + 1 :]])


def replace_ihdr(png: bytes, header: bytes) -> bytes:
    chunks = split(png)
    return assemble([(b"IHDR", header), *chunks[1:]])


def saved(mode: str, **kwargs: object) -> bytes:
    buffer = io.BytesIO()
    Image.new(mode, (WIDTH, HEIGHT)).save(buffer, "PNG", **kwargs)
    return buffer.getvalue()


def itxt_xmp(packet: bytes, *, compressed: bool) -> tuple[bytes, bytes]:
    head = b"XML:com.adobe.xmp\x00" + (b"\x01\x00" if compressed else b"\x00\x00") + b"\x00\x00"
    return b"iTXt", head + (zlib.compress(packet) if compressed else packet)


def replace_kind(png: bytes, kind: bytes, new: tuple[bytes, bytes] | None) -> bytes:
    """Swap (or drop, with None) every chunk of ``kind``; a replacement goes before IDAT."""
    kept = [c for c in split(png) if c[0] != kind]
    return with_chunks(assemble(kept), before_idat=(new,) if new else ())


def exif_png(tiff: bytes) -> bytes:
    return replace_kind(master_png(), b"eXIf", (b"eXIf", tiff))


ASCII_XRES = (
    b"MM\x00*\x00\x00\x00\x08\x00\x01\x01\x1a\x00\x02\x00\x00\x00\x01"
    b"\x00\x00\x00\x00\x00\x00\x00\x00"
)


def one_tag_tiff(tag: int, kind: int, count: int = 1, value: bytes = b"\x00" * 4) -> bytes:
    """Big-endian TIFF with one IFD entry; a mistyped tag crafts malformed EXIF."""
    entry = tag.to_bytes(2, "big") + kind.to_bytes(2, "big") + count.to_bytes(4, "big") + value
    return b"MM\x00*\x00\x00\x00\x08\x00\x01" + entry + b"\x00" * 4
