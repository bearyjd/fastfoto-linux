"""Write the corrected copies listed in a plan, leaving the library itself untouched."""

import errno
import hashlib
import logging
import os
from collections.abc import Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

from fastfoto_linux.library import fdio
from fastfoto_linux.library.exif_errors import JpegExifError
from fastfoto_linux.library.fdio import SourceFile
from fastfoto_linux.library.jpeg_exif import read_orientation, set_orientation
from fastfoto_linux.library.manifest import Manifest
from fastfoto_linux.library.plan import Action, PlanRow
from fastfoto_linux.library.safety import (
    UnsafePathError,
    assert_outside,
    check_roots,
    locate_inside,
)
from fastfoto_linux.library.tags import MAX_TAG, MIN_TAG, TAG_UPRIGHT

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


@dataclass(frozen=True)
class Outcome:
    """What happened to one ``rotate`` row; ``reason`` explains anything but ``written``."""

    path: str
    status: str
    reason: str = ""


@dataclass(frozen=True)
class ApplyResult:
    outcomes: tuple[Outcome, ...]

    def count(self, status: str) -> int:
        return sum(1 for outcome in self.outcomes if outcome.status == status)


@dataclass(frozen=True)
class _Run:
    """What every row of one ``fix`` run shares."""

    src: Path
    dest: Path
    dest_fd: int
    library: os.stat_result
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
    current = read_orientation(data)
    if (TAG_UPRIGHT if current is None else current) != row.old_tag:
        raise _Stale("the file's orientation tag is not the one in the plan")
    return set_orientation(data, row.new_tag)


def _write_row(row: PlanRow, run: _Run) -> bool:
    """Publish the copy for ``row``; False if an identical one was already there."""
    source = locate_inside(run.src, row.path)
    assert_outside(locate_inside(run.dest, row.path), run.src)
    found = _read_planned_file(row, source)
    content = _new_content(row, found.data)
    return fdio.publish(run.dest_fd, row.path, content, found, run.library)


def _record(row: PlanRow, manifest: Manifest) -> Outcome:
    try:
        manifest.record(row)
    except OSError as error:
        logger.warning("%r: written, but not added to the manifest (%s)", row.path, error)
        return Outcome(row.path, STATUS_UNLOGGED, REASON_MANIFEST)
    return Outcome(row.path, STATUS_WRITTEN)


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
    return _record(row, run.manifest) if written else Outcome(row.path, STATUS_DONE)


def apply_plan(rows: Sequence[PlanRow], src: Path, dest: Path) -> ApplyResult:
    """Write ``dest / path`` for every ``rotate`` row: the source with only its Orientation tag
    changed. A stale, unwritable or already existing target is reported; the other rows go on."""
    src_root, dest_root = check_roots(src, dest)
    library = os.stat(src_root)
    with ExitStack() as stack:
        dest_fd = fdio.open_root(dest_root, library)
        stack.callback(os.close, dest_fd)
        manifest = Manifest(dest_fd)
        stack.callback(manifest.close)
        run = _Run(src_root, dest_root, dest_fd, library, manifest)
        outcomes = tuple(_apply_row(row, run) for row in rows if row.action is Action.ROTATE)
    return ApplyResult(outcomes)
