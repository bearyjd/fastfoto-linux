"""Build JPEG test files with known orientation, and read their structure independently.

The photo is the public-domain astronaut portrait. ``displayed`` always means the picture a
viewer shows after applying the Orientation tag; ``stored`` is what the file's pixels hold.
"""

import hashlib
import io
import os
import struct
from pathlib import Path

import numpy as np
from PIL import ExifTags, Image, ImageOps

from fastfoto_linux.library.plan import Action, PlanRow
from tests.face_images import load_astronaut

ORIENTATION = 0x0112
CLOCKWISE_BY_TAG = {1: 0, 6: 90, 3: 180, 8: 270}
SOI = b"\xff\xd8"
SOS_MARKER = 0xDA
APP0, APP1, APP2 = 0xE0, 0xE1, 0xE2
EXIF_HEADER = b"Exif\x00\x00"
XMP_HEADER = b"http://ns.adobe.com/xap/1.0/\x00"
XMP_PACKET = XMP_HEADER + b"<x:xmpmeta xmlns:x='adobe:ns:meta/'><!-- test --></x:xmpmeta>"
ICC_PAYLOAD = b"ICC_PROFILE\x00\x01\x01" + bytes(range(200))
DATE_ORIGINAL = "1975:06:14 12:30:00"
MAX_APP1_PAYLOAD = 65533
SAME_PICTURE_TOLERANCE = 12.0  # mean abs difference: JPEG noise is ~2, a wrong turn is 40+


def rotate_cw(pixels: np.ndarray, degrees: int) -> np.ndarray:
    """``pixels`` turned clockwise (np.rot90 turns counter-clockwise, hence the sign)."""
    return np.ascontiguousarray(np.rot90(pixels, k=-(degrees // 90)))


def stored_pixels(displayed: np.ndarray, tag: int | None) -> np.ndarray:
    """The pixels a file must hold so that ``tag`` makes a viewer show ``displayed``."""
    return rotate_cw(displayed, -CLOCKWISE_BY_TAG.get(tag or 1, 0))


def exif_bytes(
    tag: int | None = None, *, date: bool = False, little_endian: bool = False, **fields: object
) -> bytes:
    """An Exif segment payload (with the ``Exif\\0\\0`` prefix)."""
    exif = Image.Exif()
    if little_endian:
        exif.endian = "<"
    if tag is not None:
        exif[ORIENTATION] = tag
    exif[ExifTags.Base.Make] = "TestCam"
    if date:
        exif.get_ifd(ExifTags.IFD.Exif)[ExifTags.Base.DateTimeOriginal] = DATE_ORIGINAL
    for key, value in fields.items():
        exif[ExifTags.Base[key]] = value
    return exif.tobytes()


def oversized_exif(*, tag: int | None) -> bytes:
    """An Exif payload within 4 bytes of the 65533-byte segment limit."""
    base = len(exif_bytes(tag, ImageDescription=""))
    payload = exif_bytes(tag, ImageDescription="x" * (MAX_APP1_PAYLOAD - base - 4))
    assert MAX_APP1_PAYLOAD - 12 < len(payload) <= MAX_APP1_PAYLOAD
    return payload


def segment(marker: int, payload: bytes) -> bytes:
    return bytes([0xFF, marker]) + struct.pack(">H", len(payload) + 2) + payload


def make_jpeg(
    pixels: np.ndarray,
    *,
    exif: bytes | None = None,
    xmp: bool = False,
    icc: bool = False,
    quality: int = 90,
) -> bytes:
    """A baseline JPEG of ``pixels`` with an optional Exif segment, XMP APP1 and ICC APP2."""
    buffer = io.BytesIO()
    Image.fromarray(pixels).save(buffer, "JPEG", quality=quality, exif=exif or b"")
    data = buffer.getvalue()
    extras = (segment(APP1, XMP_PACKET) if xmp else b"") + (
        segment(APP2, ICC_PAYLOAD) if icc else b""
    )
    jfif_end = 2 + 2 + struct.unpack(">H", data[4:6])[0] if data[3] == APP0 else 2
    return data[:jfif_end] + extras + data[jfif_end:]


def sideways_jpeg(deviation: int, old_tag: int | None, **options: object) -> bytes:
    """A file that currently *displays* the portrait turned ``deviation`` degrees clockwise.

    The pixels are stored so that ``old_tag`` (``None``: no Orientation tag at all) produces that.
    """
    displayed = rotate_cw(load_astronaut(), deviation)
    exif = exif_bytes(old_tag, **options) if old_tag is not None else None
    return make_jpeg(stored_pixels(displayed, old_tag), exif=exif)


def split_jpeg(data: bytes) -> tuple[list[tuple[int, bytes]], bytes]:
    """``([(marker, payload), ...] before the scan, the bytes from the SOS marker on)``."""
    assert data[:2] == SOI
    segments: list[tuple[int, bytes]] = []
    position = 2
    while data[position + 1] != SOS_MARKER:
        (length,) = struct.unpack(">H", data[position + 2 : position + 4])
        segments.append((data[position + 1], data[position + 4 : position + 2 + length]))
        position += 2 + length
    return segments, data[position:]


def exif_payloads(data: bytes) -> list[bytes]:
    return [p for marker, p in split_jpeg(data)[0] if marker == APP1 and p.startswith(EXIF_HEADER)]


def stored_array(data: bytes) -> np.ndarray:
    """The decoded pixels exactly as stored (no Orientation applied)."""
    with Image.open(io.BytesIO(data)) as image:
        return np.array(image.convert("RGB"))


def displayed_array(data: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(data)) as image:
        return np.array(ImageOps.exif_transpose(image).convert("RGB"))


def tag_of(data: bytes) -> int | None:
    with Image.open(io.BytesIO(data)) as image:
        return image.getexif().get(ORIENTATION)


def same_picture(first: np.ndarray, second: np.ndarray) -> bool:
    if first.shape != second.shape:
        return False
    return float(np.abs(first.astype(int) - second.astype(int)).mean()) < SAME_PICTURE_TOLERANCE


def upright_tag(data: bytes) -> int:
    """The tag (1, 3, 6 or 8) under which ``data`` displays the portrait upright."""
    upright = load_astronaut()
    stored = stored_array(data)
    matching = [
        t for t in CLOCKWISE_BY_TAG if same_picture(rotate_cw(stored, CLOCKWISE_BY_TAG[t]), upright)
    ]
    assert len(matching) == 1, matching
    return matching[0]


def write_file(root: Path, relative: str, data: bytes, mtime_ns: int | None = None) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    if mtime_ns is not None:
        os.utime(path, ns=(mtime_ns, mtime_ns))
    return path


def rotate_row(root: Path, relative: str, rotate_cw_by: int, old_tag: int, new_tag: int) -> PlanRow:
    """A ``rotate`` row describing the file as it is now (size, mtime and hash included)."""
    path = root / relative
    info = path.stat()
    return PlanRow(
        path=relative,
        action=Action.ROTATE,
        rotate_cw=rotate_cw_by,
        old_tag=old_tag,
        new_tag=new_tag,
        score=0.5,
        reason="test",
        size=info.st_size,
        mtime_ns=info.st_mtime_ns,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def tree_snapshot(root: Path) -> dict[str, str]:
    """Every file and folder below ``root`` mapped to a content hash (folders to ``dir``)."""
    snapshot = {}
    for path in sorted(root.rglob("*")):
        key = path.relative_to(root).as_posix()
        snapshot[key] = "dir" if path.is_dir() else hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot
