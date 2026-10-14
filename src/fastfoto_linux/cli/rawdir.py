"""Where a scan's raw pages live: a hidden temporary folder, or kept under ``.raw/<UTC time>/``."""

import contextlib
import logging
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from fastfoto_linux.output.files import sync_folders

logger = logging.getLogger(__name__)

KEPT_DIR_NAME = ".raw"
TEMP_PREFIX = ".ffscan-raw-"
# No ':' in the stamp: FAT and exFAT drives refuse it in a folder name.
STAMP_FORMAT = "%Y%m%dT%H%M%SZ"


def utc_stamp() -> str:
    """The current UTC time as a folder name; a module function so tests can pin it."""
    return datetime.now(UTC).strftime(STAMP_FORMAT)


def _kept_dir(root: Path) -> Path:
    return root / KEPT_DIR_NAME / utc_stamp()


def create_raw_dir(root: Path, *, keep: bool) -> Path:
    """A new folder for the scanner to write pages into, on ``root``'s filesystem.

    With ``keep`` it is ``root/.raw/<stamp>/`` from the start (two scans in the same second share
    it; the scanner refuses to overwrite pages that are already there); otherwise a uniquely
    named hidden folder in ``root``, which ``settle_raw_dir`` removes (or moves) when the work is
    done.
    """
    if keep:
        kept = _kept_dir(root)
        kept.mkdir(parents=True, exist_ok=True)
        return kept
    return Path(tempfile.mkdtemp(prefix=TEMP_PREFIX, dir=root))


def settle_raw_dir(raw: Path, root: Path, *, keep: bool) -> Path | None:
    """Delete ``raw`` unless ``keep``; return where its pages are now, or None if removed.

    An empty folder is never worth keeping (nor is the empty ``.raw`` it leaves behind). A
    temporary folder that is kept is moved to ``root/.raw/<stamp>/`` (a rename, they share a
    filesystem), so a raw page that failed to process is never lost: a lost page means
    rescanning the physical print.

    This runs while an error may be on its way to the user, so it never raises for a folder
    that cannot be moved or deleted: that is logged and ``raw`` is returned, as the place where
    the pages still are.
    """
    if not any(raw.iterdir()):
        _remove_empty(raw, root)
        return None
    if not keep:
        return _delete(raw, root)
    if raw.name.startswith(TEMP_PREFIX):
        return _move_to_kept(raw, root)
    return raw


def _remove_empty(raw: Path, root: Path) -> None:
    raw.rmdir()
    if raw.parent == root / KEPT_DIR_NAME:
        with contextlib.suppress(OSError):  # other scans' folders may still be in there
            raw.parent.rmdir()


def _delete(raw: Path, root: Path) -> Path | None:
    """Delete ``raw`` once the photos made from it are safely on disk.

    The album folder's entry in ``root`` is flushed first: the pages must not be gone before a
    power cut could still lose the folder that holds their photos.
    """
    try:
        sync_folders([root])
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
