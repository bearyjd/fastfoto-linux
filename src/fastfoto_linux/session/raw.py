"""Where a scan's raw pages live: a hidden temporary folder, or kept under ``.raw/<UTC time>/``."""

import contextlib
import logging
import os
import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from fastfoto_linux.documents.private_io import PRIVATE_DIR_MODE, make_private_dir
from fastfoto_linux.output.files import sync_folders
from fastfoto_linux.scanner.job import DEFAULT_FILE_PREFIX

logger = logging.getLogger(__name__)

KEPT_DIR_NAME = ".raw"
TEMP_PREFIX = ".ffscan-raw-"
# No ':' in the stamp: FAT and exFAT drives refuse it in a folder name.
STAMP_FORMAT = "%Y%m%dT%H%M%SZ"
# Every PNG ends with this IEND chunk (empty data, fixed CRC).
_PNG_END = b"\x00\x00\x00\x00IEND\xaeB`\x82"
_PAGE = re.compile(rf"{re.escape(DEFAULT_FILE_PREFIX)}-([0-9]{{4,}})\.png")


def utc_stamp() -> str:
    """The current UTC time as a folder name; a module function so tests can pin it."""
    return datetime.now(UTC).strftime(STAMP_FORMAT)


def _kept_dir(root: Path) -> Path:
    return root / KEPT_DIR_NAME / utc_stamp()


def list_pages(folder: Path) -> tuple[Path, ...]:
    """The scanner's page files in ``folder``, in page order (by number, not by file name).

    A folder that cannot be listed has no pages as far as the caller can tell: that is logged,
    not raised, as this runs while the session result is being put together.
    """
    try:
        entries = [p for p in folder.iterdir() if p.is_file()]
    except OSError as error:
        logger.error("raw folder %s cannot be listed: %s", folder, error)
        return ()
    numbered = [(int(m.group(1)), p) for p in entries if (m := _PAGE.fullmatch(p.name))]
    return tuple(path for _, path in sorted(numbered))


def is_complete_png(path: Path) -> bool:
    """Whether ``path`` ends with the PNG end chunk; a page cut off mid-write does not."""
    try:
        with path.open("rb") as page:
            page.seek(-len(_PNG_END), os.SEEK_END)  # OSError when the file is shorter
            return page.read() == _PNG_END
    except OSError:
        return False


def create_raw_dir(root: Path, *, keep: bool, private: bool = False) -> Path:
    """A new folder for the scanner to write pages into, on ``root``'s filesystem.

    With ``keep`` it is ``root/.raw/<stamp>/`` from the start (two scans in the same second share
    it; the scanner refuses to overwrite pages that are already there); otherwise a uniquely
    named hidden folder in ``root`` (always owner-only), which ``settle_raw_dir`` removes (or
    moves) when the work is done. With ``private`` a kept folder is owner-only too (mode 0700,
    also if it already existed); without it the folder gets the usual mode of a new folder.
    """
    if keep:
        kept = _kept_dir(root)
        if private:
            kept.mkdir(mode=PRIVATE_DIR_MODE, parents=True, exist_ok=True)
            make_private_dir(kept)
        else:
            kept.mkdir(parents=True, exist_ok=True)
        return kept
    return Path(tempfile.mkdtemp(prefix=TEMP_PREFIX, dir=root))


def settle_raw_dir(raw: Path, root: Path, *, keep: bool, album: Path | None = None) -> Path | None:
    """Delete ``raw`` unless ``keep``; return where its pages are now, or None if removed.

    An empty folder is never worth keeping (nor is the empty ``.raw`` it leaves behind). A
    temporary folder that is kept is moved to ``root/.raw/<stamp>/`` (a rename, they share a
    filesystem), so a raw page that failed to process is never lost: a lost page means
    rescanning the physical print.

    This runs while an error may be on its way to the user, so it never raises for a folder
    that cannot be listed, moved or deleted: that is logged and ``raw`` is returned, as the
    place where the pages still are (a folder that cannot even be listed is left alone, not
    deleted blind).

    ``root`` is the folder ``raw`` lives in. Before pages are deleted, ``album`` (the folder the
    photos made from them were written to, when that is not ``root``) is flushed as well as
    ``root``.
    """
    try:
        empty = not any(raw.iterdir())
    except OSError as error:
        logger.error("raw folder %s cannot be read, its pages are left in it: %s", raw, error)
        return raw
    if empty:
        _remove_empty(raw, root)
        return None
    if not keep:
        return _delete(raw, root, album)
    if raw.name.startswith(TEMP_PREFIX):
        return _move_to_kept(raw, root)
    return raw


def _remove_empty(raw: Path, root: Path) -> None:
    try:
        raw.rmdir()
    except OSError as error:  # no page is lost, an empty folder is just left behind
        logger.error("empty raw folder %s not removed: %s", raw, error)
        return
    if raw.parent == root / KEPT_DIR_NAME:
        with contextlib.suppress(OSError):  # other scans' folders may still be in there
            raw.parent.rmdir()


def _delete(raw: Path, root: Path, album: Path | None) -> Path | None:
    """Delete ``raw`` once the photos made from it are safely on disk.

    The folders that changed are flushed first: the pages must not be gone before a power cut
    could still lose the photos made from them, or the folder that holds the pages.
    """
    folders = [root] if album is None or album == root else [album, root]
    try:
        sync_folders(folders)
        shutil.rmtree(raw)
    except OSError as error:
        logger.error("raw pages not deleted, they are in %s: %s", raw, error)
        return raw
    return None


def _move_to_kept(raw: Path, root: Path) -> Path:
    kept = _kept_dir(root)
    try:
        kept.parent.mkdir(parents=True, exist_ok=True)
        raw.rename(kept)
    except OSError as error:
        logger.error("raw pages not moved to %s, they are still in %s: %s", kept, raw, error)
        return raw
    return kept
