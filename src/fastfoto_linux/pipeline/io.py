"""Load raw scanimage PNG frames together with their resolution, and tell when they were scanned."""

import logging
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


def _file_dpi(info: dict) -> int | None:
    raw = info.get("dpi")
    if raw is None:
        return None
    x_dpi, y_dpi = round(raw[0]), round(raw[1])
    if x_dpi != y_dpi:
        raise ValueError(f"non-square pixels are not supported: dpi {raw[0]} x {raw[1]}")
    return x_dpi


# Pillow's decompression-bomb guard (warns above ~89 Mpx, raises above ~179 Mpx) is left at its
# default on purpose: a 600 dpi frame is 47 Mpx. A 1200 dpi frame is 189 Mpx and would raise
# ``Image.DecompressionBombError``; supporting it needs a deliberate ``Image.MAX_IMAGE_PIXELS``
# change here, not a blanket opt-out.


def load_frame(path: str | Path, dpi: int | None = None) -> tuple[np.ndarray, int]:
    """Read an RGB frame and return ``(array, dpi)``.

    The resolution comes from the PNG ``pHYs`` chunk, rounded to a whole dpi (scanimage writes
    599.9988 for 600 dpi). An explicit ``dpi`` argument takes precedence over the file; if neither
    is available a ``ValueError`` is raised.
    """
    with Image.open(path) as image:
        if image.mode != "RGB":
            raise ValueError(f"{path}: expected an RGB image, got mode {image.mode}")
        resolved = dpi if dpi is not None else _file_dpi(image.info)
        if resolved is None:
            raise ValueError(f"{path}: file has no dpi metadata; pass dpi explicitly")
        if resolved <= 0:
            raise ValueError(f"{path}: dpi must be positive, got {resolved}")
        return np.array(image), resolved


def scan_time(page: Path) -> datetime | None:
    """When the page file was written: the scan time, as the file system knows it.

    None when the file cannot be inspected.
    """
    try:
        return datetime.fromtimestamp(page.stat().st_mtime)
    except OSError as error:
        logger.debug("cannot read the time of %s: %s", page.name, error)
        return None
