"""Find the JPEG files of a library; nothing is read except directory listings."""

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from fastfoto_linux.library.safety import FolderId, folder_id

logger = logging.getLogger(__name__)

JPEG_SUFFIXES = frozenset({".jpg", ".jpeg"})
HIDDEN_PREFIX = "."
METADATA_FOLDERS = frozenset({"@eaDir"})  # Synology's thumbnail folders


@dataclass(frozen=True)
class WalkResult:
    """``jpegs`` are paths relative to the walked folder (POSIX, sorted); ``skipped_folders``
    counts the hidden and metadata folders that were not entered for their JPEGs.

    ``folders`` holds the identity (device and inode) of the walked folder and of every folder
    below it, the skipped ones and their subfolders included: all of them are the library.
    ``unlisted_folders`` counts every folder that could not be listed, skipped ones included
    (``unreadable_folders`` is only those whose files would have counted).
    """

    jpegs: tuple[str, ...]
    other_formats: int
    symlinks: int
    unreadable_folders: int
    skipped_folders: int = 0
    folders: frozenset[FolderId] = frozenset()
    unlisted_folders: int = 0


def _is_skipped_folder(name: str) -> bool:
    return name.startswith(HIDDEN_PREFIX) or name in METADATA_FOLDERS


def _list_folder(folder: Path, *, report: bool) -> list[os.DirEntry[str]] | None:
    """The entries of ``folder``; ``None`` if it cannot be read (said once, if ``report``)."""
    try:
        with os.scandir(folder) as listing:
            return list(listing)
    except OSError as error:
        if report:
            logger.warning("cannot read a folder: %s", error.strerror or error)
        return None


def _entry_id(entry: os.DirEntry[str]) -> FolderId | None:
    try:
        return folder_id(entry.stat(follow_symlinks=False))
    except OSError:  # gone since it was listed
        return None


def walk_library(src: Path) -> WalkResult:
    """Every JPEG below ``src`` (symlinks are never followed, other formats are only counted).

    Hidden folders (``.name``) and ``@eaDir`` folders are not searched for JPEGs; they are counted
    instead, and still walked for the identities of the folders in them.
    """
    jpegs: list[str] = []
    other_formats = symlinks = unreadable = skipped = unlisted = 0
    folders = {folder_id(os.stat(src))}
    pending = [(src, True)]  # (folder, whether its files count)
    while pending:
        folder, counted = pending.pop()
        entries = _list_folder(folder, report=counted)
        if entries is None:
            unreadable += counted
            unlisted += 1
            continue
        for entry in entries:
            if entry.is_symlink():
                symlinks += counted
            elif entry.is_dir(follow_symlinks=False):
                hidden = not counted or _is_skipped_folder(entry.name)
                skipped += counted and hidden
                if (identity := _entry_id(entry)) is not None:
                    folders.add(identity)
                pending.append((Path(entry.path), not hidden))
            elif counted and entry.is_file(follow_symlinks=False):
                if Path(entry.name).suffix.lower() in JPEG_SUFFIXES:
                    jpegs.append(Path(entry.path).relative_to(src).as_posix())
                else:
                    other_formats += 1
    return WalkResult(
        tuple(sorted(jpegs)),
        other_formats,
        symlinks,
        unreadable,
        skipped,
        frozenset(folders),
        unlisted,
    )
