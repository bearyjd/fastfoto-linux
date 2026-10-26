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
from fastfoto_linux.documents.despeckle import DespeckleStatus, despeckle_white
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
    despeckle: bool = False  # the effective switch it was made with (False unless black and white)


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


def effective_despeckle(flag: bool, mode: ColourMode) -> bool:
    """Whether despeckle counts for a page written in ``mode``: only black and white has it."""
    return flag and mode is ColourMode.BW


def encode_page(
    page: LoadedPage,
    requested: ColourMode,
    cleanup: CleanupPolicy = CleanupPolicy.OFF,
    *,
    despeckle: bool = False,
    cancel: threading.Event | None = None,
) -> EncodedPage:
    """Write ``page`` in the mode ``output_mode(page.kind, requested)`` allows.

    Colour and grey become a baseline JPEG that the PDF embeds as it is. Black and white is a
    1-bit CCITT G4 TIFF: an adaptive threshold for colour or grey pages, the pixels unchanged
    for a page that was already 1-bit. ``cleanup`` lightens the paper of a grey or colour page
    (see ``cleanup``; a ``cancel`` is honoured inside it) and never changes a black and white
    one. ``despeckle`` removes small isolated specks from a black and white page (see
    ``despeckle``). The input is not modified.
    """
    mode = output_mode(page.kind, requested)
    height, width = page.pixels.shape[:2]
    pixels = render_page(page, mode, cleanup, despeckle=despeckle, cancel=cancel)
    data = _group4(pixels == WHITE, page.dpi) if mode is ColourMode.BW else _jpeg(pixels, page.dpi)
    return EncodedPage(
        data,
        mode,
        width,
        height,
        page.dpi,
        effective_cleanup(cleanup, mode),
        effective_despeckle(despeckle, mode),
    )


def render_page(  # noqa: PLR0913 - the hooks are the interface
    page: LoadedPage,
    actual_mode: ColourMode,
    cleanup: CleanupPolicy = CleanupPolicy.OFF,
    *,
    despeckle: bool = False,
    cancel: threading.Event | None = None,
    on_cleanup: Callable[[CleanupStatus], None] | None = None,
    on_despeckle: Callable[[DespeckleStatus], None] | None = None,
) -> np.ndarray:
    """Render full-resolution output pixels before encoding or preview downsampling.

    A grey or colour page is cleaned by ``cleanup`` after the mode is rendered; black and white
    is never touched by it. ``despeckle`` removes small isolated specks from a black and white
    render only. A page they leave alone is the plain render, byte for byte.
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
    if mode is not ColourMode.BW:
        if on_despeckle is not None:
            on_despeckle(DespeckleStatus.NOT_BW if despeckle else DespeckleStatus.OFF)
        return page.pixels.copy() if mode is ColourMode.COLOUR else _grey(page).copy()
    grey = _grey(page)
    plain = grey.copy() if page.kind is ColourMode.BW else _binarised(grey, page.dpi)
    if not despeckle:
        if on_despeckle is not None:
            on_despeckle(DespeckleStatus.OFF)
        return plain
    source = page.pixels if page.kind is ColourMode.COLOUR else None
    result = despeckle_white(plain == WHITE, page.dpi, source=source, cancel=cancel)
    logger.debug("despeckle %s removed %d", result.status, result.removed)
    if on_despeckle is not None:
        on_despeckle(result.status)
    if result.pixels is None:
        return plain
    return _white_to_pixels(result.pixels)


def _binarised(grey: np.ndarray, dpi: int) -> np.ndarray:
    return _white_to_pixels(binarise(grey, dpi))


def _white_to_pixels(white: np.ndarray) -> np.ndarray:
    return np.where(white, WHITE, 0).astype(np.uint8)
