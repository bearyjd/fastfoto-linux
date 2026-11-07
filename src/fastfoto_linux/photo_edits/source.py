"""Decode and identify a retained original without rewriting it."""

import hashlib
import importlib
import io
import struct
import warnings
from pathlib import Path

import numpy as np
from PIL import ExifTags, Image, ImageOps, UnidentifiedImageError

from fastfoto_linux.photo_edits.model import (
    MAX_SOURCE_BYTES,
    MAX_SOURCE_PIXELS,
    PhotoEditError,
    PhotoSource,
    finite,
)
from fastfoto_linux.photo_edits.png_guard import (
    BAD_METADATA,
    MAX_METADATA_CHUNK,
    PNG_SIGNATURE,
    check_png,
)

FALLBACK_DPI = 300.0
SWAPPED_ORIENTATIONS = frozenset({5, 6, 7, 8})
CM_PER_INCH = 2.54
JFIF_UNIT_INCHES = 1
JFIF_UNIT_CENTIMETERS = 2
EXIF_UNIT_INCHES = 2
EXIF_UNIT_CENTIMETERS = 3
DPI_SNAP = 0.01
UNSUPPORTED = "the retained source is not a supported JPEG or PNG"


def source_bytes(path: Path) -> bytes:
    """Bound file reads before allocating source/metadata buffers."""
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_SOURCE_BYTES + 1)
    except OSError as error:
        raise PhotoEditError("the retained source cannot be read") from error
    if not data or len(data) > MAX_SOURCE_BYTES:
        raise PhotoEditError("the retained source is empty or too large")
    return data


def verify_source(source: PhotoSource) -> None:
    """Refuse publication after the source was replaced or modified."""
    if hashlib.sha256(source_bytes(source.path)).hexdigest() != source.sha256:
        raise PhotoEditError("the retained source hash changed; reopen the original")


def _dpi_pair(values: tuple[object, object], scale: float) -> tuple[float, float]:
    x, y = values
    x, y = finite(float(x) * scale, "DPI"), finite(float(y) * scale, "DPI")
    if x <= 0 or y <= 0:
        raise PhotoEditError("invalid DPI")
    return x, y


def _png_dpi(image: Image.Image) -> tuple[float, float] | None:
    """pHYs in metres reads back as 599.9988 for 600; snap to the integer when that close."""
    if image.format != "PNG":
        return None
    try:
        x, y = (float(value) for value in image.info["dpi"])
        snapped = tuple(round(v) if abs(v - round(v)) < DPI_SNAP else v for v in (x, y))
        return _dpi_pair(snapped, 1.0)
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def _dpi(image: Image.Image, notes: list[str]) -> tuple[float, float]:
    png = _png_dpi(image)
    if png is not None:
        return png
    # Pillow's EXIF-only info["dpi"] repeats XResolution on both axes, so read both explicitly.
    exif = image.getexif()
    candidates = (
        (
            image.info.get("jfif_unit"),
            image.info.get("jfif_density"),
            {JFIF_UNIT_INCHES: 1.0, JFIF_UNIT_CENTIMETERS: CM_PER_INCH},
        ),
        (
            exif.get(ExifTags.Base.ResolutionUnit),
            (exif.get(ExifTags.Base.XResolution), exif.get(ExifTags.Base.YResolution)),
            {EXIF_UNIT_INCHES: 1.0, EXIF_UNIT_CENTIMETERS: CM_PER_INCH},
        ),
    )
    for unit, values, scales in candidates:
        try:
            if unit in scales:
                return _dpi_pair(values, scales[unit])
        except (TypeError, ValueError, OverflowError, ZeroDivisionError):
            continue
    notes.append(
        "Original resolution is missing, relative or invalid; using 300 DPI for eye detection."
    )
    return FALLBACK_DPI, FALLBACK_DPI


def _profile(image: Image.Image, notes: list[str]) -> bytes | None:
    profile = image.info.get("icc_profile")
    if profile is None:
        return None
    try:
        cms = importlib.import_module("PIL.ImageCms")
        cms.ImageCmsProfile(io.BytesIO(profile))
    except (ImportError, OSError, TypeError, ValueError):
        notes.append(
            "The original color profile is invalid or unsupported; the edited copy omits it."
        )
        return None
    return profile


def _xmp(image: Image.Image) -> bytes:
    if image.format == "PNG":
        packet = image.info.get("XML:com.adobe.xmp", "")
        raw = packet.encode("utf-8") if isinstance(packet, str) else b""
        if len(raw) > MAX_METADATA_CHUNK:  # Pillow has already inflated a compressed iTXt
            raise PhotoEditError(BAD_METADATA)
        return raw
    return image.info.get("xmp", b"")


def _decode(path: Path, data: bytes) -> PhotoSource:
    notes: list[str] = []
    if data.startswith(PNG_SIGNATURE):
        check_png(data)
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(data)) as image:
            if (
                image.format not in {"JPEG", "PNG"}
                or image.mode != "RGB"
                or image.width * image.height > MAX_SOURCE_PIXELS
            ):
                raise PhotoEditError(
                    "photo review requires a bounded retained original RGB JPEG or PNG"
                )
            if image.format == "PNG":
                image.load()  # text chunks after IDAT are only read once pixels are
            exif = image.getexif()
            orientation = exif.get(274, 1)
            if type(orientation) is not int or orientation not in range(1, 9):
                raise PhotoEditError("the source has an unsupported EXIF orientation")
            x, y = _dpi(image, notes)
            if orientation in SWAPPED_ORIENTATIONS:
                x, y = y, x
            profile = _profile(image, notes)
            pixels = np.array(ImageOps.exif_transpose(image).convert("RGB"))
            return PhotoSource(
                path=path,
                sha256=hashlib.sha256(data).hexdigest(),
                byte_size=len(data),
                width=pixels.shape[1],
                height=pixels.shape[0],
                dpi_x=x,
                dpi_y=y,
                effective_dpi=max(x, y),
                pixels=pixels,
                orientation=orientation,
                exif=exif.tobytes(),
                xmp=_xmp(image),
                format=image.format,
                icc_profile=profile,
                warnings=tuple(notes),
            )


def load_source(path: Path, *, expected_sha256: str | None = None) -> PhotoSource:
    """Hash source bytes and normalize EXIF orientation into the canonical pixel space."""
    path = path.absolute()
    data = source_bytes(path)
    if expected_sha256 is not None and hashlib.sha256(data).hexdigest() != expected_sha256:
        raise PhotoEditError("the retained source hash changed")
    try:
        return _decode(path, data)
    except PhotoEditError:
        raise
    except (
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        ValueError,
        TypeError,
        struct.error,
        AttributeError,
        KeyError,
        IndexError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as error:
        raise PhotoEditError(UNSUPPORTED) from error
