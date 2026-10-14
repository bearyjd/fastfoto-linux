"""Where a scan's raw pages live: a hidden temporary folder, or kept under ``.raw/<UTC time>/``."""

import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

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

    With ``keep`` it is ``root/.raw/<stamp>/`` from the start; otherwise a uniquely named hidden
    folder in ``root``, which ``settle_raw_dir`` removes (or moves) when the work is done.
    """
    if keep:
        kept = _kept_dir(root)
        kept.mkdir(parents=True)
        return kept
    return Path(tempfile.mkdtemp(prefix=TEMP_PREFIX, dir=root))


def settle_raw_dir(raw: Path, root: Path, *, keep: bool) -> Path | None:
    """Delete ``raw`` unless ``keep``; return where its pages are now, or None if removed.

    An empty folder is never worth keeping. A temporary folder that is kept is moved to
    ``root/.raw/<stamp>/`` (a rename, they share a filesystem), so a raw page that failed to
    process is never lost: a lost page means rescanning the physical print.
    """
    if not any(raw.iterdir()):
        raw.rmdir()
        return None
    if not keep:
        shutil.rmtree(raw)
        return None
    if raw.name.startswith(TEMP_PREFIX):
        kept = _kept_dir(root)
        kept.parent.mkdir(exist_ok=True)
        raw.rename(kept)
        return kept
    return raw
