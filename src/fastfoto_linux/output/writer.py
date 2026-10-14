"""Write scanned photos to album folders as JPEG with EXIF and XMP metadata."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from fastfoto_linux.output.metadata import DateRange, PhotoDate
from fastfoto_linux.output.naming import next_index  # noqa: F401

DEFAULT_QUALITY = 95


def _now() -> datetime:
    return datetime.now()


@dataclass(frozen=True)
class WrittenFiles:
    directory: Path
    index: int
    original: Path | None
    enhanced: Path | None
    back: Path | None

    @property
    def paths(self) -> tuple[Path, ...]:
        raise NotImplementedError


def write_photo(  # noqa: PLR0913
    front: np.ndarray,
    *,
    dpi: int,
    output_root: Path,
    back: np.ndarray | None = None,
    enhanced: np.ndarray | None = None,
    album: str | None = None,
    prefix: str | None = None,
    date: PhotoDate | DateRange | None = None,
    notes: str | None = None,
    scanned_at: datetime | None = None,
    quality: int = DEFAULT_QUALITY,
    keep_original: bool = True,
) -> WrittenFiles:
    """Write one photo; see the GREEN implementation."""
    raise NotImplementedError
