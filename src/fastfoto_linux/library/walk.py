"""Find the JPEG files of a library; nothing is read except directory listings."""

from dataclasses import dataclass
from pathlib import Path

JPEG_SUFFIXES = frozenset({".jpg", ".jpeg"})


@dataclass(frozen=True)
class WalkResult:
    """``jpegs`` are paths relative to the walked folder (POSIX, sorted)."""

    jpegs: tuple[str, ...]
    other_formats: int
    symlinks: int
    unreadable_folders: int


def walk_library(src: Path) -> WalkResult:
    """Every JPEG below ``src`` (symlinks are never followed, other formats are only counted)."""
    raise NotImplementedError
