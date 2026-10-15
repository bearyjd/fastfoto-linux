"""Write the corrected copies listed in a plan, leaving the library itself untouched."""

import errno
import hashlib
import logging
import os
import re
import stat
from collections.abc import Sequence
from contextlib import ExitStack
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath

from fastfoto_linux.library import confine, fdio
from fastfoto_linux.library.exif_errors import JpegExifError
from fastfoto_linux.library.fdio import SourceFile
from fastfoto_linux.library.jpeg_exif import Layout, read_orientation, set_orientation
from fastfoto_linux.library.manifest import Manifest
from fastfoto_linux.library.plan import Action, PlanRow
from fastfoto_linux.library.safety import (
    Library,
    UnsafePathError,
    assert_outside,
    check_roots,
    locate_inside,
)
from fastfoto_linux.library.tags import MAX_TAG, MIN_TAG, TAG_UPRIGHT
from fastfoto_linux.library.walk import walk_library

logger = logging.getLogger(__name__)

STATUS_WRITTEN = "written"
STATUS_DONE = "done"  # an identical copy was already there (an earlier, interrupted run)
STATUS_UNLOGGED = "unlogged"  # the copy was written but its manifest row was not
STATUS_STALE = "stale"
STATUS_EXISTS = "exists"
STATUS_FAILED = "failed"
REASON_EXISTS = "the destination file already exists"
REASON_IO = "io-error"
REASON_MANIFEST = "manifest-error"
REASON_UNSAFE_DESTINATION = "unsafe-destination"
OWNER_RWX = 0o700
# What an interrupted run leaves behind: ".<name>.<8 hex digits>.tmp".
STAGING_NAME = re.compile(
    rf"\..+\.[0-9a-f]{{{2 * fdio.TOKEN_BYTES}}}{re.escape(fdio.STAGING_SUFFIX)}"
)


@dataclass(frozen=True)
class Outcome:
    """What happened to one ``rotate`` row; ``reason`` explains anything but ``written``."""

    path: str
    status: str
    reason: str = ""


@dataclass(frozen=True)
class ApplyResult:
    outcomes: tuple[Outcome, ...]
    leftover_staging: int = 0  # staging files of a killed run found in the folders written to

    def count(self, status: str) -> int:
        return sum(1 for outcome in self.outcomes if outcome.status == status)


@dataclass(frozen=True)
class _Run:
    """What every row of one ``fix`` run shares."""

    src: Path
    dest: Path
    dest_fd: int
    library: Library
    manifest: Manifest


class _Stale(Exception):
    """The file is no longer the one the plan was made for."""


def _read_source(source: Path) -> SourceFile:
    try:
        return fdio.read_regular(source)
    except FileNotFoundError:
        raise _Stale("the file is gone") from None
    except fdio.TooLargeError:
        raise _Stale("the file is too large to process") from None
    except fdio.NotRegularFileError:
        raise _Stale("the file is now not a regular file") from None
    except fdio.ChangedWhileReadingError:
        raise _Stale("the file changed while it was being read") from None
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise _Stale("the file is now a link") from None
        raise


def _read_planned_file(row: PlanRow, source: Path) -> SourceFile:
    """The file at ``source`` if it is still exactly what ``row`` describes; else ``_Stale``."""
    found = _read_source(source)
    if found.size != row.size:
        raise _Stale("the file size changed since the check")
    if found.mtime_ns != row.mtime_ns:
        raise _Stale("the file was modified since the check")
    if not row.sha256 or hashlib.sha256(found.data).hexdigest() != row.sha256:
        raise _Stale("the file content differs from the check")
    return found


def _new_content(row: PlanRow, data: bytes) -> bytes:
    """``data`` with the planned tag; ``_Stale`` if the plan does not fit the file."""
    if row.old_tag is None or row.new_tag is None or not MIN_TAG <= row.new_tag <= MAX_TAG:
        raise _Stale("the plan row has no usable old_tag and new_tag")
    layout = Layout.of(data)
    current = read_orientation(data, layout)
    if (TAG_UPRIGHT if current is None else current) != row.old_tag:
        raise _Stale("the file's orientation tag is not the one in the plan")
    return set_orientation(data, row.new_tag, layout)


def _folder_modes(src: Path, relative: str) -> tuple[int, ...]:
    """The modes of the library folders above ``relative``, outermost first (new copies' folders
    get these); a folder that cannot be examined is left out and gets the default."""
    modes = []
    folder = src
    for part in PurePosixPath(relative).parent.parts:
        folder = folder / part
        try:
            modes.append(stat.S_IMODE(os.stat(folder).st_mode))
        except OSError:
            break
    return tuple(modes)


def _write_row(row: PlanRow, run: _Run) -> bool:
    """Publish the copy for ``row``; False if an identical one was already there."""
    source = locate_inside(run.src, row.path)
    assert_outside(locate_inside(run.dest, row.path), run.src)
    found = _read_planned_file(row, source)
    content = _new_content(row, found.data)
    found = replace(found, folder_modes=_folder_modes(run.src, row.path))
    return fdio.publish(run.dest_fd, row.path, content, found, run.library)


def _record(row: PlanRow, manifest: Manifest, status: str) -> Outcome:
    """Add ``row`` to the manifest; ``status`` is the outcome if that works."""
    try:
        manifest.record(row)
    except OSError as error:
        logger.warning("%r: copy is there, but not added to the manifest (%s)", row.path, error)
        return Outcome(row.path, STATUS_UNLOGGED, REASON_MANIFEST)
    return Outcome(row.path, status)


def _apply_row(row: PlanRow, run: _Run) -> Outcome:
    try:
        written = _write_row(row, run)
    except _Stale as stale:
        return Outcome(row.path, STATUS_STALE, str(stale))
    except UnsafePathError:
        return Outcome(row.path, STATUS_FAILED, REASON_UNSAFE_DESTINATION)
    except JpegExifError as error:
        return Outcome(row.path, STATUS_FAILED, error.reason)
    except FileExistsError:
        return Outcome(row.path, STATUS_EXISTS, REASON_EXISTS)
    except OSError as error:
        logger.warning("%r: %s", row.path, error.strerror or error)
        return Outcome(row.path, STATUS_FAILED, REASON_IO)
    return _record(row, run.manifest, STATUS_WRITTEN if written else STATUS_DONE)


def _count_leftovers(dest: Path, rows: Sequence[PlanRow]) -> int:
    """Staging files of a killed run in the folders the rotate rows write to (not deleted)."""
    folders = {PurePosixPath(row.path).parent for row in rows if row.action is Action.ROTATE}
    found = 0
    for folder in sorted({PurePosixPath(), *folders}):
        try:
            names = os.listdir(dest / folder)
        except OSError:
            continue
        found += sum(1 for name in names if STAGING_NAME.fullmatch(name))
    return found


def apply_plan(
    rows: Sequence[PlanRow], src: Path, dest: Path, *, make_dest: bool = False
) -> ApplyResult:
    """Write ``dest / path`` for every ``rotate`` row: the source with only its Orientation tag
    changed. A stale, unwritable or already existing target is reported; the other rows go on.

    ``make_dest`` creates ``dest`` (and any missing folders above it) when it does not exist.
    """
    src_root, dest_root = check_roots(src, dest)
    # Every folder of the library, so that a bind mount of any of them is told from a new folder.
    library = Library(os.stat(src_root), walk_library(src_root).folders)
    if make_dest:  # made through descriptors too, then opened (and checked) like any other
        mode = stat.S_IMODE(library.root.st_mode) | OWNER_RWX
        os.close(confine.open_folder(dest_root, create=True, last_mode=mode, library=library))
    with ExitStack() as stack:
        dest_fd = fdio.open_root(dest_root, library)
        stack.callback(os.close, dest_fd)
        manifest = Manifest(dest_fd)
        stack.callback(manifest.close)
        run = _Run(src_root, dest_root, dest_fd, library, manifest)
        outcomes = tuple(_apply_row(row, run) for row in rows if row.action is Action.ROTATE)
    return ApplyResult(outcomes, _count_leftovers(dest_root, rows))
