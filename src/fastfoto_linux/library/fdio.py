"""File access through open descriptors, so a path swapped mid-run is never followed.

Reading opens the file once without following a link, checks the open file is a regular one and
reads from that descriptor. Writing opens the destination folder from ``/`` down (see ``confine``),
then every folder below it one step at a time with ``dir_fd`` and ``O_NOFOLLOW``, so a folder
replaced by a link between the checks and the write is refused instead of followed. A new file is
written under a private staging name and published with ``link`` (which never replaces) while it
is still private; only then does it get the source's mode and times, through the open descriptor.
"""

import contextlib
import enum
import errno
import functools
import logging
import os
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from fastfoto_linux.library import confine
from fastfoto_linux.library.safety import LibraryRef, UnsafePathError, as_library

logger = logging.getLogger(__name__)

MAX_FILE_BYTES = 128 * 1024 * 1024  # a photo larger than this is skipped, never read into memory
READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
# Reading the library's files must not change their access times; only the owner (or root) may ask
# for that. (The access times of its folders still change when they are listed.)
NO_ACCESS_TIME = getattr(os, "O_NOATIME", 0)
FOLDER_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
CREATE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
PRIVATE_MODE = 0o600
PERMISSION_BITS = 0o777  # leaves out setuid, setgid and the sticky bit
OWNER_RWX = 0o700  # a folder we create must stay writable for us, whatever the source's mode
ROOT_UID = 0  # may change the mode and times of any file
STAGING_SUFFIX = ".tmp"
TOKEN_BYTES = 4
# link() errors that mean "this filesystem has no hard links" (FAT/exFAT, some network mounts).
_NO_HARD_LINKS = frozenset({errno.EPERM, errno.ENOTSUP, errno.ENOSYS})
# fsync() on a folder is not supported on every filesystem; that is not a failure.
_NO_FOLDER_SYNC = frozenset({errno.EINVAL, errno.ENOTSUP, errno.ENOSYS})
# Filesystems without Unix permissions refuse chmod; the times still carry over.
_NO_MODES = frozenset({errno.EPERM, errno.ENOTSUP})
_APPLIED = "now match the source's"
_NOT_APPLIED = "could not be set"
# What opening a link or a plain file as a folder (without following links) reports.
_NOT_A_FOLDER = frozenset({errno.ELOOP, errno.ENOTDIR})


class NotRegularFileError(OSError):
    """The path is not a plain file (a pipe, a device, a folder)."""


class TooLargeError(OSError):
    """The file is bigger than ``MAX_FILE_BYTES``."""


class ChangedWhileReadingError(OSError):
    """The file's size changed while it was being read."""


class MetadataRefusedError(FileExistsError):
    """An identical file is there, our own, and the system refused to give it the source's mode or
    times. ``strerror`` says which of the two it got."""


class Placed(enum.Enum):
    """What became of a copy: written now, or an identical file was already there."""

    WRITTEN = enum.auto()
    IDENTICAL = enum.auto()  # there already, with (or given) the source's mode and times
    IDENTICAL_NOT_OURS = enum.auto()  # there already, another user's: its mode and times left as is


@dataclass(frozen=True)
class SourceFile:
    """A file read through one descriptor: its bytes and the metadata of that same open file."""

    data: bytes
    size: int
    mtime_ns: int
    atime_ns: int
    mode: int
    folder_modes: tuple[int, ...] = ()  # the modes of the folders above it, outermost first


def _open_for_reading(path: Path) -> int:
    """``path`` opened without following a link, and without touching its access time if allowed."""
    if NO_ACCESS_TIME:
        try:
            return os.open(path, READ_FLAGS | NO_ACCESS_TIME)
        except OSError as error:
            if error.errno != errno.EPERM:  # EPERM: not the owner, so the time cannot be spared
                raise
    return os.open(path, READ_FLAGS)


def read_regular(path: Path) -> SourceFile:
    """The bytes and metadata of the regular file at ``path`` (a link is not followed)."""
    fd = _open_for_reading(path)
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise NotRegularFileError(errno.EINVAL, "not a regular file")
        if info.st_size > MAX_FILE_BYTES:
            raise TooLargeError(errno.EFBIG, "file too large")
        data = handle.read(info.st_size + 1)
    if len(data) != info.st_size:
        raise ChangedWhileReadingError(errno.EAGAIN, "file changed while being read")
    return SourceFile(data, info.st_size, info.st_mtime_ns, info.st_atime_ns, info.st_mode)


def open_root(dest: Path, library: LibraryRef) -> int:
    """A descriptor for the destination folder, opened from ``/`` without following links.

    UnsafePathError if it is the library or lies anywhere below it.
    """
    fd = confine.open_folder(dest)
    try:
        confine.refuse_inside(fd, library)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _refuse_library(fd: int, library: LibraryRef) -> None:
    info, inside = os.fstat(fd), as_library(library)
    if inside.contains(info):
        raise UnsafePathError("refusing to write: a destination folder is the library itself")
    inside.refuse_unproven(info)


def _open_folder(parent_fd: int, name: str) -> int:
    try:
        return os.open(name, FOLDER_FLAGS, dir_fd=parent_fd)
    except OSError as error:
        if error.errno in _NOT_A_FOLDER:
            raise UnsafePathError(
                f"{name!r} in the destination is a link or not a folder"
            ) from error
        raise


def _enter_folder(parent_fd: int, name: str, source_mode: int | None) -> int:
    """The folder ``name`` below ``parent_fd``, made if it is missing; never through a link.

    A new folder gets ``source_mode`` (the library folder's), always with the owner's full access.
    """
    try:
        return _open_folder(parent_fd, name)
    except FileNotFoundError:
        pass
    created = True
    try:
        os.mkdir(name, dir_fd=parent_fd)
    except FileExistsError:
        created = False
    fd = _open_folder(parent_fd, name)
    if created and source_mode is not None:
        _set_mode(fd, (source_mode & PERMISSION_BITS) | OWNER_RWX)
    return fd


def publish(
    root_fd: int, relative: str, content: bytes, source: SourceFile, library: LibraryRef
) -> Placed:
    """Write ``content`` as ``relative`` below the destination, with ``source``'s mode and times.

    ``WRITTEN`` when the file was written now; otherwise a file with exactly these bytes was
    already there (``IDENTICAL``, or ``IDENTICAL_NOT_OURS`` when it is another user's and so could
    not be given the mode and times). A different file already there raises FileExistsError and
    is left alone. A folder on the way that is a link, or the library itself, raises
    UnsafePathError.
    """
    pure = PurePosixPath(relative)
    with contextlib.ExitStack() as stack:
        folder_fd = root_fd
        for depth, part in enumerate(pure.parent.parts):
            modes = source.folder_modes
            folder_fd = _enter_folder(folder_fd, part, modes[depth] if depth < len(modes) else None)
            stack.callback(os.close, folder_fd)
            _refuse_library(folder_fd, library)
        return _publish_in(folder_fd, pure.name, content, source, library)


def _publish_in(
    folder_fd: int, name: str, content: bytes, source: SourceFile, library: LibraryRef
) -> Placed:
    # The folder was checked when it was opened; it may have been moved into the library since,
    # so it is checked again before anything is written to it and again before the copy is linked.
    confine.refuse_inside(folder_fd, library)
    staging = f".{name}.{secrets.token_hex(TOKEN_BYTES)}{STAGING_SUFFIX}"
    fd = os.open(staging, CREATE_FLAGS, PRIVATE_MODE, dir_fd=folder_fd)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            confine.refuse_inside(folder_fd, library)
            placed = link_new(folder_fd, staging, name, content, source)
            if placed is Placed.WRITTEN:
                _finish_published(handle.fileno(), folder_fd, name, source)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(staging, dir_fd=folder_fd)
    if placed is Placed.WRITTEN:
        sync_folder(folder_fd)
    return placed


def _finish_published(fd: int, folder_fd: int, name: str, source: SourceFile) -> None:
    """Give the published file ``source``'s mode and times; if that fails take it back."""
    try:
        _copy_metadata(fd, source)
        os.fsync(fd)
    except BaseException:
        with contextlib.suppress(OSError):
            published = os.stat(name, dir_fd=folder_fd, follow_symlinks=False)
            if os.path.samestat(published, os.fstat(fd)):
                os.unlink(name, dir_fd=folder_fd)
        raise


@functools.cache
def _warn_modes_unsupported() -> None:
    """Said once per run: the copies get the default mode instead of the source's."""
    logger.warning("the destination does not accept file permissions; copies get its default mode")


def _set_mode(fd: int, mode: int) -> None:
    try:
        os.fchmod(fd, mode)
    except OSError as error:
        if error.errno not in _NO_MODES:
            raise
        _warn_modes_unsupported()


def _copy_metadata(fd: int, source: SourceFile) -> None:
    """Mode (without setuid/setgid) and both times of ``source``; no extended attributes."""
    _set_mode(fd, source.mode & PERMISSION_BITS)
    os.utime(fd, ns=(source.atime_ns, source.mtime_ns))


def link_new(
    folder_fd: int, staging: str, name: str, content: bytes, source: SourceFile | None = None
) -> Placed:
    """Link the staged file in as ``name``: ``WRITTEN``. If a file with exactly ``content`` is
    there already, it gets ``source``'s mode and times, if given and different (see
    ``_already_there``). A different file there is FileExistsError."""
    try:
        os.link(staging, name, src_dir_fd=folder_fd, dst_dir_fd=folder_fd, follow_symlinks=False)
    except FileExistsError:
        return _already_there(folder_fd, name, content, source)
    except OSError as error:
        if error.errno not in _NO_HARD_LINKS:
            raise
        return _reserve_then_rename(folder_fd, staging, name, content, source)
    return Placed.WRITTEN


def _reserve_then_rename(
    folder_fd: int, staging: str, name: str, content: bytes, source: SourceFile | None
) -> Placed:
    """For filesystems without hard links: claim the name exclusively, then swap the file in."""
    try:
        os.close(os.open(name, CREATE_FLAGS, PRIVATE_MODE, dir_fd=folder_fd))
    except FileExistsError:
        if not _is_placeholder(folder_fd, name):
            return _already_there(folder_fd, name, content, source)
    try:
        os.rename(staging, name, src_dir_fd=folder_fd, dst_dir_fd=folder_fd)
    except BaseException:
        os.unlink(name, dir_fd=folder_fd)
        raise
    return Placed.WRITTEN


def _is_placeholder(folder_fd: int, name: str) -> bool:
    """Whether ``name`` is an empty regular file: what a crash after the claim leaves behind."""
    try:
        info = os.stat(name, dir_fd=folder_fd, follow_symlinks=False)
    except OSError:
        return False
    return stat.S_ISREG(info.st_mode) and info.st_size == 0


def _exists(name: str) -> FileExistsError:
    return FileExistsError(errno.EEXIST, "the destination file already exists", name)


def _already_there(folder_fd: int, name: str, content: bytes, source: SourceFile | None) -> Placed:
    """``IDENTICAL`` if the existing file holds exactly ``content``; otherwise FileExistsError.

    A run killed between linking a copy and giving it its mode and times leaves exactly such a
    file; with ``source``, the file gets its mode and times now, through the descriptor that
    just confirmed what it holds. If it is another user's, it is left as it is (see
    ``_repair_metadata``) and counts as done all the same: the content is right, and no later
    run could change that.
    """
    try:
        fd = os.open(name, READ_FLAGS, dir_fd=folder_fd)
    except OSError:
        raise _exists(name) from None
    with os.fdopen(fd, "rb") as handle:
        try:
            info = os.fstat(handle.fileno())
            same = (
                stat.S_ISREG(info.st_mode)
                and info.st_size == len(content)
                and handle.read(len(content) + 1) == content
            )
        except OSError:
            same = False
        if not same:
            raise _exists(name)
        if source is None or not _differs(info, source):
            return Placed.IDENTICAL
        return _repair_metadata(handle.fileno(), info, name, source)


def _repair_metadata(fd: int, info: os.stat_result, name: str, source: SourceFile) -> Placed:
    """``source``'s mode and times on the file ``fd``. They are only ours to set on our own
    files: another user's is left exactly as it is (``IDENTICAL_NOT_OURS``). If the system refuses
    on our own, MetadataRefusedError says what the file has and has not got by then."""
    if os.geteuid() not in (ROOT_UID, info.st_uid):
        return Placed.IDENTICAL_NOT_OURS
    try:
        _copy_metadata(fd, source)
    except PermissionError as error:
        raise _refused(os.fstat(fd), name, source, error) from None
    return Placed.IDENTICAL


def _refused(
    now: os.stat_result, name: str, source: SourceFile, error: PermissionError
) -> MetadataRefusedError:
    """What the file ``now`` has of ``source``'s mode and times, after the system refused."""
    mode_set = stat.S_IMODE(now.st_mode) == source.mode & PERMISSION_BITS
    times_set = now.st_mtime_ns == source.mtime_ns
    reason = (
        "identical file already there; "
        f"its permissions {_APPLIED if mode_set else _NOT_APPLIED}, "
        f"its times {_APPLIED if times_set else _NOT_APPLIED} ({error.strerror or error})"
    )
    return MetadataRefusedError(errno.EEXIST, reason, name)


def _differs(info: os.stat_result, source: SourceFile) -> bool:
    """Whether the file's mode or modification time is not the source's (reading changes atime)."""
    return stat.S_IMODE(info.st_mode) != source.mode & PERMISSION_BITS or (
        info.st_mtime_ns != source.mtime_ns
    )


def sync_folder(fd: int) -> None:
    """Flush a folder's entries to disk, where the filesystem can."""
    try:
        os.fsync(fd)
    except OSError as error:
        if error.errno not in _NO_FOLDER_SYNC:
            raise
