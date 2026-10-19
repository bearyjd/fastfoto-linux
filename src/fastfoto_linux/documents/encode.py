"""Encode one page for the PDF: JPEG for colour and grey, lossless CCITT G4 for black and white."""

import io
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

from fastfoto_linux.documents.bilevel import binarise
from fastfoto_linux.documents.loader import WHITE, LoadedPage
from fastfoto_linux.documents.modes import ColourMode, output_mode

JPEG_QUALITY = 85
TIFF_CCITT_G4 = "group4"


@dataclass(frozen=True)
class EncodedPage:
    """One page ready for the PDF: encoded bytes, how it was written, size and resolution."""

    data: bytes
    mode: ColourMode
    width: int
    height: int
    dpi: int


def _jpeg(pixels: np.ndarray, dpi: int) -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(pixels).save(buffer, "JPEG", quality=JPEG_QUALITY, dpi=(dpi, dpi))
    return buffer.getvalue()


def _group4(white: np.ndarray, dpi: int) -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(white).save(buffer, "TIFF", compression=TIFF_CCITT_G4, dpi=(dpi, dpi))
    return buffer.getvalue()


def _grey(page: LoadedPage) -> np.ndarray:
    if page.kind is ColourMode.COLOUR:
        return cv2.cvtColor(page.pixels, cv2.COLOR_RGB2GRAY)
    return page.pixels


def encode_page(page: LoadedPage, requested: ColourMode) -> EncodedPage:
    """Write ``page`` in the mode ``output_mode(page.kind, requested)`` allows.

    Colour and grey become a baseline JPEG that the PDF embeds as it is. Black and white is a
    1-bit CCITT G4 TIFF: an adaptive threshold for colour or grey pages, the pixels unchanged
    for a page that was already 1-bit. The input is not modified.
    """
    mode = output_mode(page.kind, requested)
    height, width = page.pixels.shape[:2]
    if mode is ColourMode.COLOUR:
        data = _jpeg(page.pixels, page.dpi)
    elif mode is ColourMode.GREY:
        data = _jpeg(_grey(page), page.dpi)
    elif page.kind is ColourMode.BW:
        data = _group4(page.pixels == WHITE, page.dpi)
    else:
        data = _group4(binarise(_grey(page), page.dpi), page.dpi)
    return EncodedPage(data, mode, width, height, page.dpi)


def render_page(page: LoadedPage, actual_mode: ColourMode) -> np.ndarray:
    """Render full-resolution output pixels before encoding or preview downsampling."""
    raise NotImplementedError("document output preview rendering is not implemented")
