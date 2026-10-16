"""Encode one page for the PDF: JPEG for colour and grey, lossless CCITT G4 for black and white."""

from dataclasses import dataclass

from fastfoto_linux.documents.loader import LoadedPage
from fastfoto_linux.documents.modes import ColourMode

JPEG_QUALITY = 85


@dataclass(frozen=True)
class EncodedPage:
    """One page ready for the PDF: encoded bytes, how it was written, size and resolution."""

    data: bytes
    mode: ColourMode
    width: int
    height: int
    dpi: int


def encode_page(page: LoadedPage, requested: ColourMode) -> EncodedPage:
    """Write ``page`` in the mode ``output_mode(page.kind, requested)`` allows.

    Colour and grey become a baseline JPEG that the PDF embeds as it is. Black and white is a
    1-bit CCITT G4 TIFF: an adaptive threshold for colour or grey pages, the pixels unchanged
    for a page that was already 1-bit. The input is not modified.
    """
    raise NotImplementedError
