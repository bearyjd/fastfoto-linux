"""Read one scanned page (PNG) into an array, or refuse it with a clear message.

Accepted: RGB, 8-bit grey and 1-bit PNGs that say how many dots per inch they hold. Anything
else (palette, alpha, 16-bit, other formats, a missing or absurd resolution) is refused by
name, so a run stops before it writes a PDF with a page missing.
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from fastfoto_linux.documents.errors import UnsupportedPageError
from fastfoto_linux.documents.modes import ColourMode

MIN_DPI = 50
MAX_DPI = 2400
DPI_AGREEMENT = 1.0  # horizontal and vertical resolution may differ by this much (rounding)
PNG_FORMAT = "PNG"
_KINDS = {"RGB": ColourMode.COLOUR, "L": ColourMode.GREY, "1": ColourMode.BW}
WHITE = 255  # a white pixel of a 1-bit page, as the loader gives it (black is 0)


@dataclass(frozen=True, eq=False)
class LoadedPage:
    """Pixels of one page: RGB ``HxWx3`` uint8 for colour, ``HxW`` uint8 for grey, and ``HxW``
    uint8 holding only 0 and 255 for a page that was 1-bit."""

    pixels: np.ndarray
    kind: ColourMode
    dpi: int


@dataclass(frozen=True)
class PageInfo:
    """What a page file's header says, without decoding the pixels."""

    kind: ColourMode
    dpi: int
    width: int
    height: int


def _open(path: Path) -> Image.Image:
    try:
        return Image.open(path)
    except (OSError, Image.DecompressionBombError) as error:
        raise UnsupportedPageError(f"{path.name}: cannot be read as a PNG ({error})") from error


def _resolution(path: Path, image: Image.Image, fallback_dpi: int | None) -> int:
    declared = image.info.get("dpi")
    if declared is None:
        if fallback_dpi is None:
            raise UnsupportedPageError(
                f"{path.name}: the PNG does not say its resolution; pass --dpi to name it"
            )
        return fallback_dpi
    horizontal, vertical = float(declared[0]), float(declared[1])
    if abs(horizontal - vertical) > DPI_AGREEMENT:
        raise UnsupportedPageError(
            f"{path.name}: the PNG has different horizontal and vertical resolution "
            f"({horizontal:.0f} and {vertical:.0f} dpi)"
        )
    dpi = round(horizontal)
    if not MIN_DPI <= dpi <= MAX_DPI:
        raise UnsupportedPageError(
            f"{path.name}: the PNG has an implausible resolution of {dpi} dpi "
            f"(expected {MIN_DPI}-{MAX_DPI})"
        )
    return dpi


def _inspect(path: Path, image: Image.Image, fallback_dpi: int | None) -> PageInfo:
    if image.format != PNG_FORMAT:
        raise UnsupportedPageError(f"{path.name}: not a PNG file (it is {image.format})")
    kind = _KINDS.get(image.mode)
    if kind is None:
        raise UnsupportedPageError(
            f"{path.name}: unsupported PNG mode {image.mode}; need RGB, 8-bit grey or 1-bit"
        )
    return PageInfo(kind, _resolution(path, image, fallback_dpi), image.width, image.height)


def _decode(path: Path, image: Image.Image) -> None:
    try:
        image.load()
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError) as error:
        raise UnsupportedPageError(f"{path.name}: cannot be decoded ({error})") from error


def inspect_page(path: Path, *, fallback_dpi: int | None = None, decode: bool = False) -> PageInfo:
    """Check a page file: a PNG that is RGB, 8-bit grey or 1-bit, with a resolution.

    ``fallback_dpi`` is used only when the file carries no resolution. With ``decode`` the
    pixels are decoded (and dropped) as well, which finds a truncated or corrupt file that the
    header alone does not show. Raises UnsupportedPageError naming the file and the reason.
    """
    with _open(path) as image:
        info = _inspect(path, image, fallback_dpi)
        if decode:
            _decode(path, image)
        return info


def load_page(path: Path, *, fallback_dpi: int | None = None) -> LoadedPage:
    """Decode a page file; the same checks as ``inspect_page`` apply."""
    with _open(path) as image:
        info = _inspect(path, image, fallback_dpi)
        _decode(path, image)
        pixels = np.array(image)
    if info.kind is ColourMode.BW:
        pixels = np.where(pixels, WHITE, 0).astype(np.uint8)
    return LoadedPage(pixels, info.kind, info.dpi)
