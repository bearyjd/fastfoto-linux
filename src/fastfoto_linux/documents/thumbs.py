"""Thumbnails of the trimmed pages, for a reviewer's grid: small private JPEGs.

Made from the page the analysis has already decoded, so no page is read a second time.
"""

import io
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from fastfoto_linux.documents.private_io import ensure_private_dir, write_private_atomic

THUMB_MAX_PX = 480  # the long side of a thumbnail (a smaller page is not enlarged)
THUMB_QUALITY = 80


def thumbnail_name(number: int) -> str:
    """The file name of the thumbnail of raw page ``number``: fixed by the number."""
    return f"page-{number:04d}.jpg"


def thumbnail_bytes(pixels: np.ndarray) -> bytes:
    """``pixels`` (RGB or grey, 8 bit) as a JPEG with its long side at most ``THUMB_MAX_PX``."""
    height, width = pixels.shape[:2]
    scale = THUMB_MAX_PX / max(height, width)
    if scale < 1:
        size = (max(1, round(width * scale)), max(1, round(height * scale)))
        pixels = cv2.resize(pixels, size, interpolation=cv2.INTER_AREA)
    buffer = io.BytesIO()
    Image.fromarray(pixels).save(buffer, "JPEG", quality=THUMB_QUALITY)
    return buffer.getvalue()


def write_thumbnail(pixels: np.ndarray, folder: Path, number: int) -> str:
    """Write the thumbnail of page ``number`` into ``folder`` (made owner-only) and return its
    file name. Raises OSError when it cannot be written."""
    ensure_private_dir(folder)
    name = thumbnail_name(number)
    write_private_atomic(folder / name, thumbnail_bytes(pixels))
    return name
