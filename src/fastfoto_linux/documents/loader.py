"""Read one scanned page (PNG) into an array, or refuse it with a clear message."""

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from fastfoto_linux.documents.modes import ColourMode


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


def inspect_page(path: Path, *, fallback_dpi: int | None = None) -> PageInfo:
    """Check a page file's header: a PNG that is RGB, 8-bit grey or 1-bit, with a resolution.

    ``fallback_dpi`` is used only when the file carries no resolution. Raises
    UnsupportedPageError naming the file and the reason.
    """
    raise NotImplementedError


def load_page(path: Path, *, fallback_dpi: int | None = None) -> LoadedPage:
    """Decode a page file; the same checks as ``inspect_page`` apply."""
    raise NotImplementedError
