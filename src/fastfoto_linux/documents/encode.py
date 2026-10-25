"""Encode one page for the PDF: JPEG for colour and grey, lossless CCITT G4 for black and white."""

import io
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

from fastfoto_linux.documents.bilevel import binarise
from fastfoto_linux.documents.cleanup import CleanupStatus, clean_pixels
from fastfoto_linux.documents.loader import WHITE, LoadedPage
from fastfoto_linux.documents.modes import CleanupPolicy, ColourMode, output_mode

logger = logging.getLogger(__name__)

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
    cleanup: CleanupPolicy = (
        CleanupPolicy.OFF
    )  # the level it was made with (OFF for black and white)


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


def effective_cleanup(policy: CleanupPolicy, mode: ColourMode) -> CleanupPolicy:
    """The cleanup level that counts for a page written in ``mode``: black and white has none."""
    return CleanupPolicy.OFF if mode is ColourMode.BW else policy


def encode_page(
    page: LoadedPage,
    requested: ColourMode,
    cleanup: CleanupPolicy = CleanupPolicy.OFF,
    *,
    cancel: threading.Event | None = None,
) -> EncodedPage:
    """Write ``page`` in the mode ``output_mode(page.kind, requested)`` allows.

    Colour and grey become a baseline JPEG that the PDF embeds as it is. Black and white is a
    1-bit CCITT G4 TIFF: an adaptive threshold for colour or grey pages, the pixels unchanged
    for a page that was already 1-bit. ``cleanup`` lightens the paper of a grey or colour page
    (see ``cleanup``; a ``cancel`` is honoured inside it) and never changes a black and white
    one. The input is not modified.
    """
    mode = output_mode(page.kind, requested)
    height, width = page.pixels.shape[:2]
    pixels = render_page(page, mode, cleanup, cancel=cancel)
    data = _group4(pixels == WHITE, page.dpi) if mode is ColourMode.BW else _jpeg(pixels, page.dpi)
    return EncodedPage(data, mode, width, height, page.dpi, effective_cleanup(cleanup, mode))


def render_page(
    page: LoadedPage,
    actual_mode: ColourMode,
    cleanup: CleanupPolicy = CleanupPolicy.OFF,
    *,
    cancel: threading.Event | None = None,
    on_cleanup: Callable[[CleanupStatus], None] | None = None,
) -> np.ndarray:
    """Render full-resolution output pixels before encoding or preview downsampling.

    A grey or colour page is cleaned by ``cleanup`` after the mode is rendered; black and white
    is never touched. A page cleanup leaves alone is the plain render, byte for byte.
    """
    mode = output_mode(page.kind, actual_mode)
    status = CleanupStatus.BW if mode is ColourMode.BW else CleanupStatus.OFF
    if mode is not ColourMode.BW and cleanup is not CleanupPolicy.OFF:
        cleaned = clean_pixels(page.pixels, page.dpi, mode, cleanup, cancel=cancel)
        logger.debug("cleanup %s", cleaned.status)
        status = cleaned.status
        if on_cleanup is not None:
            on_cleanup(status)
        if cleaned.pixels is not None:
            return cleaned.pixels
    elif on_cleanup is not None:
        on_cleanup(status)
    if mode is ColourMode.COLOUR:
        return page.pixels.copy()
    grey = _grey(page)
    if mode is ColourMode.GREY or page.kind is ColourMode.BW:
        return grey.copy()
    return np.where(binarise(grey, page.dpi), WHITE, 0).astype(np.uint8)
