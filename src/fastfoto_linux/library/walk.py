"""Find the JPEG files of a library; nothing is read except directory listings."""

import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

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
    jpegs: list[str] = []
    other_formats = symlinks = unreadable = 0
    pending = [src]
    while pending:
        try:
            with os.scandir(pending.pop()) as listing:
                entries = list(listing)
        except OSError as error:
            unreadable += 1
            logger.warning("cannot read a folder: %s", error.strerror or error)
            continue
        for entry in entries:
            if entry.is_symlink():
                symlinks += 1
            elif entry.is_dir(follow_symlinks=False):
                pending.append(Path(entry.path))
            elif entry.is_file(follow_symlinks=False):
                if Path(entry.name).suffix.lower() in JPEG_SUFFIXES:
                    jpegs.append(Path(entry.path).relative_to(src).as_posix())
                else:
                    other_formats += 1
    return WalkResult(tuple(sorted(jpegs)), other_formats, symlinks, unreadable)
