"""Owner-only folders and files: how the sidecar and the thumbnails are written.

A folder is made with mode 0700 and a file with mode 0600 whatever the umask. A file is written
to a temporary name in its folder and moved into place (``os.replace``), so a reader sees the old
file or the new one and a crash leaves the old one. The temporary name is no page name.
"""

import contextlib
import os
import tempfile
from pathlib import Path

PRIVATE_DIR_MODE = 0o700  # owner only: the raw pages of a document may be a letter or a bill
PRIVATE_FILE_MODE = 0o600
TEMP_PREFIX = ".tmp-"
TEMP_SUFFIX = ".part"


def make_private_dir(folder: Path) -> None:
    """Set the owner-only mode on ``folder`` itself, never on what a link there points to.

    ``mkdir`` leaves the mode of a folder that already exists alone, and ``chmod`` follows a
    link, so a link planted as ``.raw/<stamp>`` would have the mode of its target changed (and
    the pages written there). ``O_NOFOLLOW`` refuses a link, with no gap between the check and
    the change.
    """
    try:
        descriptor = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as error:
        raise OSError(
            error.errno, f"{folder} is not a folder of its own (a link?): {error.strerror}"
        ) from error
    try:
        os.fchmod(descriptor, PRIVATE_DIR_MODE)
    finally:
        os.close(descriptor)


def ensure_private_dir(folder: Path) -> None:
    """``folder`` exists (its parent must) and is owner-only."""
    folder.mkdir(mode=PRIVATE_DIR_MODE, exist_ok=True)
    make_private_dir(folder)


def write_private_atomic(path: Path, data: bytes) -> None:
    """``data`` becomes the content of ``path`` (mode 0600) in one step; on any failure the old
    file is as it was and the temporary file is gone."""
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=TEMP_PREFIX, suffix=TEMP_SUFFIX)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as file:
            os.fchmod(file.fileno(), PRIVATE_FILE_MODE)
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            temporary.unlink()
        raise
