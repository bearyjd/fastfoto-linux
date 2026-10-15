"""Find the JPEG files of a library; nothing is read except directory listings."""

import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

JPEG_SUFFIXES = frozenset({".jpg", ".jpeg"})
HIDDEN_PREFIX = "."
METADATA_FOLDERS = frozenset({"@eaDir"})  # Synology's thumbnail folders


@dataclass(frozen=True)
class WalkResult:
    """``jpegs`` are paths relative to the walked folder (POSIX, sorted); ``skipped_folders``
    counts the hidden and metadata folders that were not entered."""

    jpegs: tuple[str, ...]
    other_formats: int
    symlinks: int
    unreadable_folders: int
    skipped_folders: int = 0


def _is_skipped_folder(name: str) -> bool:
    return name.startswith(HIDDEN_PREFIX) or name in METADATA_FOLDERS


def walk_library(src: Path) -> WalkResult:
    """Every JPEG below ``src`` (symlinks are never followed, other formats are only counted).

    Hidden folders (``.name``) and ``@eaDir`` folders are not entered; they are counted instead.
    """
    jpegs: list[str] = []
    other_formats = symlinks = unreadable = skipped = 0
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
                if _is_skipped_folder(entry.name):
                    skipped += 1
                else:
                    pending.append(Path(entry.path))
            elif entry.is_file(follow_symlinks=False):
                if Path(entry.name).suffix.lower() in JPEG_SUFFIXES:
                    jpegs.append(Path(entry.path).relative_to(src).as_posix())
                else:
                    other_formats += 1
    return WalkResult(tuple(sorted(jpegs)), other_formats, symlinks, unreadable, skipped)
