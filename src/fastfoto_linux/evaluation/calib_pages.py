"""Decode a document page from verified corpus bytes (PNG only), with the loader's rules.

The same kinds and resolution rules as ``documents.loader`` (RGB, 8-bit grey or 1-bit; a stated
resolution of 50 to 2400 dpi; at least 10 mm each way), but from bytes already checked against
the manifest, with the red-eye pixel cap, and with messages that never name a file.
"""

import io
import warnings

import numpy as np
from PIL import Image

from fastfoto_linux.documents.loader import (
    DPI_AGREEMENT,
    MAX_DPI,
    MIN_DPI,
    PNG_FORMAT,
    WHITE,
    LoadedPage,
    require_size,
)
from fastfoto_linux.documents.modes import ColourMode
from fastfoto_linux.evaluation.redeye_images import MAX_SOURCE_PIXELS

_KINDS = {"RGB": ColourMode.COLOUR, "L": ColourMode.GREY, "1": ColourMode.BW}


def _dpi(image: Image.Image, fallback: int | None) -> int:
    declared = image.info.get("dpi")
    if declared is None:
        if fallback is None:
            raise ValueError("the page does not say its resolution")
        return fallback
    horizontal, vertical = float(declared[0]), float(declared[1])
    dpi = round(horizontal)
    if abs(horizontal - vertical) > DPI_AGREEMENT or not MIN_DPI <= dpi <= MAX_DPI:
        raise ValueError("the page has an unusable resolution")
    return dpi


def decode_page(data: bytes, fallback_dpi: int | None) -> LoadedPage:
    """The page in ``data``; ``fallback_dpi`` (from an annotation) only when the PNG has none.
    Raises ``ValueError`` (or a Pillow error) for anything the document tools would refuse."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(data), formats=[PNG_FORMAT]) as image:
            kind = _KINDS.get(image.mode)
            if kind is None or getattr(image, "is_animated", False):
                raise ValueError("the page is not an RGB, grey or 1-bit single-frame PNG")
            if image.width * image.height > MAX_SOURCE_PIXELS:
                raise ValueError("the page is too large")
            dpi = _dpi(image, fallback_dpi)
            require_size(image.width, image.height, dpi)
            image.load()
            pixels = np.array(image)
    if kind is ColourMode.BW:
        pixels = np.where(pixels, WHITE, 0).astype(np.uint8)
    return LoadedPage(pixels, kind, dpi)
