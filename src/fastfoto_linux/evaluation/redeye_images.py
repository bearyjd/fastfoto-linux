"""A safe image loader: contained paths, byte and pixel caps, no surprises."""

import hashlib
import io
import os
import stat
import struct
import warnings
from collections.abc import Callable
from pathlib import Path

import numpy as np
from PIL import Image, UnidentifiedImageError

MAX_SOURCE_BYTES = 256 * 1024 * 1024
MAX_SOURCE_PIXELS = 89_000_000
_MODES = ("RGB", "L", "P")
_FORMATS = ("PNG", "JPEG", "TIFF")  # no EPS (Ghostscript), no animated formats
_PNG_HEADER_BYTES = 24
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class BudgetExceeded(Exception):  # not a ValueError: decoding must not turn it into "corrupt"
    """The caller's decoded-pixel budget would be exceeded by this image."""


class ImageError(Exception):
    """An image that cannot be evaluated; ``code`` is the reason code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def read_contained(root: Path, rel: str) -> bytes:
    """The bytes of regular file ``rel`` under ``root``; symlinks are followed, then contained."""
    try:
        base = root.resolve(strict=True)
        target = (base / rel).resolve(strict=True)
    except OSError as error:
        raise ImageError("missing") from error
    if base not in target.parents:
        raise ImageError("unsafe_path")
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(target, flags)
    except OSError as error:
        raise ImageError("unsafe_path") from error
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ImageError("unsafe_path")
        if info.st_size > MAX_SOURCE_BYTES:
            raise ImageError("too_large")
        data = handle.read(min(info.st_size, MAX_SOURCE_BYTES) + 1)  # sized: no 256 MB buffer
    if len(data) > MAX_SOURCE_BYTES:
        raise ImageError("too_large")
    return data


def _png_pixels(data: bytes) -> int | None:
    """Width x height from a PNG's IHDR, which Pillow only exposes once the chunks are valid."""
    if (
        len(data) >= _PNG_HEADER_BYTES
        and data.startswith(_PNG_SIGNATURE)
        and data[12:16] == b"IHDR"
    ):
        width, height = struct.unpack(">II", data[16:_PNG_HEADER_BYTES])
        return width * height
    return None


def decode_image(data: bytes, charge: Callable[[int], None] | None = None) -> np.ndarray:
    """Decode to RGB uint8, checking the header size before the pixels are loaded.

    ``charge`` is called with the header's pixel count before any pixel is decoded (it may
    raise ``BudgetExceeded``). Images whose header cannot be read are not charged.
    """
    declared = _png_pixels(data)
    if declared is not None and declared > MAX_SOURCE_PIXELS:
        raise ImageError("too_large")
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        try:
            with Image.open(io.BytesIO(data), formats=_FORMATS) as image:
                width, height = image.size
                if width * height > MAX_SOURCE_PIXELS:
                    raise ImageError("too_large")
                if charge is not None:
                    charge(width * height)
                if getattr(image, "n_frames", 1) > 1:
                    raise ImageError("multi_frame")
                if image.mode not in _MODES or (image.mode == "P" and "transparency" in image.info):
                    raise ImageError("bad_mode")
                image.load()
                rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
        except (Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
            raise ImageError("too_large") from error
        except UnidentifiedImageError as error:
            raise ImageError("bad_format") from error
        except (OSError, SyntaxError, ValueError, EOFError) as error:
            raise ImageError("corrupt") from error
    if rgb.shape != (height, width, 3):
        raise ImageError("corrupt")
    return rgb


def load_image(
    root: Path, rel: str, sha256: str, charge: Callable[[int], None] | None = None
) -> np.ndarray:
    """The verified RGB array of ``rel`` under ``root``; ``ImageError`` says why not."""
    data = read_contained(root, rel)
    if hashlib.sha256(data).hexdigest() != sha256:
        raise ImageError("hash_mismatch")
    return decode_image(data, charge)
