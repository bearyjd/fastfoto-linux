"""Write the corrected copies listed in a plan, leaving the library itself untouched."""

import csv
import hashlib
import logging
import shutil
import stat
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from fastfoto_linux.library.jpeg_exif import JpegExifError, read_orientation, set_orientation
from fastfoto_linux.library.plan import ENCODING, ENCODING_ERRORS, Action, PlanRow
from fastfoto_linux.library.safety import assert_outside, check_roots, locate_inside
from fastfoto_linux.library.tags import MAX_TAG, MIN_TAG, TAG_UPRIGHT
from fastfoto_linux.output.errors import OutputCollisionError
from fastfoto_linux.output.files import write_new_files

logger = logging.getLogger(__name__)

MANIFEST_NAME = "fastfoto-reorient-manifest.csv"
MANIFEST_COLUMNS = ("path", "old_tag", "new_tag")
STATUS_WRITTEN = "written"
STATUS_STALE = "stale"
STATUS_EXISTS = "exists"
STATUS_FAILED = "failed"
REASON_EXISTS = "the destination file already exists"
REASON_IO = "io-error"


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


class _Stale(Exception):
    """The file is no longer the one the plan was made for."""


def _read_planned_file(row: PlanRow, source: Path) -> bytes:
    """The bytes of ``source`` if it is still exactly what ``row`` describes; else ``_Stale``."""
    try:
        info = source.lstat()
    except FileNotFoundError:
        raise _Stale("the file is gone") from None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise _Stale("the file is now a link or not a regular file")
    if info.st_size != row.size:
        raise _Stale("the file size changed since the check")
    if info.st_mtime_ns != row.mtime_ns:
        raise _Stale("the file was modified since the check")
    data = source.read_bytes()
    if not row.sha256 or hashlib.sha256(data).hexdigest() != row.sha256:
        raise _Stale("the file content differs from the check")
    return data


def _new_content(row: PlanRow, data: bytes) -> bytes:
    """``data`` with the planned tag; ``_Stale`` if the plan does not fit the file."""
    if row.old_tag is None or row.new_tag is None or not MIN_TAG <= row.new_tag <= MAX_TAG:
        raise _Stale("the plan row has no usable old_tag and new_tag")
    current = read_orientation(data)
    if (TAG_UPRIGHT if current is None else current) != row.old_tag:
        raise _Stale("the file's orientation tag is not the one in the plan")
    return set_orientation(data, row.new_tag)


def _append_manifest(dest: Path, row: PlanRow) -> None:
    path = dest / MANIFEST_NAME
    is_new = not path.exists()
    with path.open("a", encoding=ENCODING, errors=ENCODING_ERRORS, newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        if is_new:
            writer.writerow(MANIFEST_COLUMNS)
        writer.writerow([row.path, row.old_tag, row.new_tag])


def _write_copy(source: Path, target: Path, content: bytes) -> None:
    """Publish ``content`` as ``target`` with ``source``'s times and mode; never replaces."""
    target.parent.mkdir(parents=True, exist_ok=True)
    write_new_files([(target, content)])
    try:
        shutil.copystat(source, target)
    except OSError:
        target.unlink(missing_ok=True)
        raise


def _apply_row(row: PlanRow, src: Path, dest: Path) -> Outcome:
    source = locate_inside(src, row.path)
    target = locate_inside(dest, row.path)
    assert_outside(target, src)
    try:
        content = _new_content(row, _read_planned_file(row, source))
        _write_copy(source, target, content)
    except _Stale as stale:
        return Outcome(row.path, STATUS_STALE, str(stale))
    except JpegExifError as error:
        return Outcome(row.path, STATUS_FAILED, error.reason)
    except OutputCollisionError:
        return Outcome(row.path, STATUS_EXISTS, REASON_EXISTS)
    except OSError as error:
        logger.warning("%s: %s", row.path, error.strerror or error)
        return Outcome(row.path, STATUS_FAILED, REASON_IO)
    _append_manifest(dest, row)
    return Outcome(row.path, STATUS_WRITTEN)


def apply_plan(rows: Sequence[PlanRow], src: Path, dest: Path) -> ApplyResult:
    """Write ``dest / path`` for every ``rotate`` row: the source with only its Orientation tag
    changed. A stale, unwritable or already existing target is reported; the other rows go on."""
    src_root, dest_root = check_roots(src, dest)
    outcomes = tuple(
        _apply_row(row, src_root, dest_root) for row in rows if row.action is Action.ROTATE
    )
    return ApplyResult(outcomes)
