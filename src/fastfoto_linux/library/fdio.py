"""File access through open descriptors, so a path swapped mid-run is never followed.

Reading opens the file once without following a link, checks the open file is a regular one and
reads from that descriptor. Writing opens the destination folder, then every folder below it one
step at a time with ``dir_fd`` and ``O_NOFOLLOW``, so a folder replaced by a link between the
checks and the write is refused instead of followed. A new file is written under a private staging
name, given the source's mode and times, and published with ``link`` (which never replaces).
"""

import contextlib
import errno
import functools
import logging
import os
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from fastfoto_linux.library import safety
from fastfoto_linux.library.safety import UnsafePathError

logger = logging.getLogger(__name__)

MAX_FILE_BYTES = 512 * 1024 * 1024  # a photo larger than this is skipped, never read into memory
READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
FOLDER_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
CREATE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
PRIVATE_MODE = 0o600
PERMISSION_BITS = 0o777  # leaves out setuid, setgid and the sticky bit
STAGING_SUFFIX = ".tmp"
TOKEN_BYTES = 4
# link() errors that mean "this filesystem has no hard links" (FAT/exFAT, some network mounts).
_NO_HARD_LINKS = frozenset({errno.EPERM, errno.ENOTSUP, errno.ENOSYS})
# fsync() on a folder is not supported on every filesystem; that is not a failure.
_NO_FOLDER_SYNC = frozenset({errno.EINVAL, errno.ENOTSUP, errno.ENOSYS})
# Filesystems without Unix permissions refuse chmod; the times still carry over.
_NO_MODES = frozenset({errno.EPERM, errno.ENOTSUP})
# What opening a link or a plain file as a folder (without following links) reports.
_NOT_A_FOLDER = frozenset({errno.ELOOP, errno.ENOTDIR})


class NotRegularFileError(OSError):
    """The path is not a plain file (a pipe, a device, a folder)."""


class TooLargeError(OSError):
    """The file is bigger than ``MAX_FILE_BYTES``."""


class ChangedWhileReadingError(OSError):
    """The file's size changed while it was being read."""


@dataclass(frozen=True)
class SourceFile:
    """A file read through one descriptor: its bytes and the metadata of that same open file."""

    data: bytes
    size: int
    mtime_ns: int
    atime_ns: int
    mode: int


def read_regular(path: Path) -> SourceFile:
    """The bytes and metadata of the regular file at ``path`` (a link is not followed)."""
    fd = os.open(path, READ_FLAGS)
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


def open_root(dest: Path, library: os.stat_result) -> int:
    """A descriptor for the destination folder; it must not be the library itself."""
    fd = os.open(dest, FOLDER_FLAGS)
    try:
        _refuse_library(fd, library)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _refuse_library(fd: int, library: os.stat_result) -> None:
    if safety.same_directory(os.fstat(fd), library):
        raise UnsafePathError("refusing to write: a destination folder is the library itself")


def _open_folder(parent_fd: int, name: str) -> int:
    try:
        return os.open(name, FOLDER_FLAGS, dir_fd=parent_fd)
    except OSError as error:
        if error.errno in _NOT_A_FOLDER:
            raise UnsafePathError(
                f"{name!r} in the destination is a link or not a folder"
            ) from error
        raise


def _enter_folder(parent_fd: int, name: str) -> int:
    """The folder ``name`` below ``parent_fd``, made if it is missing; never through a link."""
    try:
        return _open_folder(parent_fd, name)
    except FileNotFoundError:
        pass
    with contextlib.suppress(FileExistsError):
        os.mkdir(name, dir_fd=parent_fd)
    return _open_folder(parent_fd, name)


def publish(
    root_fd: int, relative: str, content: bytes, source: SourceFile, library: os.stat_result
) -> bool:
    """Write ``content`` as ``relative`` below the destination, with ``source``'s mode and times.

    True when the file was written now; False when a file with exactly these bytes was already
    there. A different file already there raises FileExistsError and is left alone. A folder on
    the way that is a link, or the library itself, raises UnsafePathError.
    """
    pure = PurePosixPath(relative)
    with contextlib.ExitStack() as stack:
        folder_fd = root_fd
        for part in pure.parent.parts:
            folder_fd = _enter_folder(folder_fd, part)
            stack.callback(os.close, folder_fd)
            _refuse_library(folder_fd, library)
        return _publish_in(folder_fd, pure.name, content, source)


def _publish_in(folder_fd: int, name: str, content: bytes, source: SourceFile) -> bool:
    staging = f".{name}.{secrets.token_hex(TOKEN_BYTES)}{STAGING_SUFFIX}"
    fd = os.open(staging, CREATE_FLAGS, PRIVATE_MODE, dir_fd=folder_fd)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            _copy_metadata(handle.fileno(), source)
            os.fsync(handle.fileno())
        written = _link_new(folder_fd, staging, name, content)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(staging, dir_fd=folder_fd)
    if written:
        sync_folder(folder_fd)
    return written


@functools.cache
def _warn_modes_unsupported() -> None:
    """Said once per run: the copies get the default mode instead of the source's."""
    logger.warning("the destination does not accept file permissions; copies get its default mode")


def _copy_metadata(fd: int, source: SourceFile) -> None:
    """Mode (without setuid/setgid) and both times of ``source``; no extended attributes."""
    try:
        os.fchmod(fd, source.mode & PERMISSION_BITS)
    except OSError as error:
        if error.errno not in _NO_MODES:
            raise
        _warn_modes_unsupported()
    os.utime(fd, ns=(source.atime_ns, source.mtime_ns))


def _link_new(folder_fd: int, staging: str, name: str, content: bytes) -> bool:
    try:
        os.link(staging, name, src_dir_fd=folder_fd, dst_dir_fd=folder_fd, follow_symlinks=False)
    except FileExistsError:
        return _already_there(folder_fd, name, content)
    except OSError as error:
        if error.errno not in _NO_HARD_LINKS:
            raise
        return _reserve_then_rename(folder_fd, staging, name, content)
    return True


def _reserve_then_rename(folder_fd: int, staging: str, name: str, content: bytes) -> bool:
    """For filesystems without hard links: claim the name exclusively, then swap the file in."""
    try:
        os.close(os.open(name, CREATE_FLAGS, PRIVATE_MODE, dir_fd=folder_fd))
    except FileExistsError:
        return _already_there(folder_fd, name, content)
    try:
        os.rename(staging, name, src_dir_fd=folder_fd, dst_dir_fd=folder_fd)
    except BaseException:
        os.unlink(name, dir_fd=folder_fd)
        raise
    return True


def _already_there(folder_fd: int, name: str, content: bytes) -> bool:
    """False if the existing file holds exactly ``content``; otherwise FileExistsError."""
    try:
        fd = os.open(name, READ_FLAGS, dir_fd=folder_fd)
        with os.fdopen(fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            same = (
                stat.S_ISREG(info.st_mode)
                and info.st_size == len(content)
                and handle.read(len(content) + 1) == content
            )
    except OSError:
        same = False
    if not same:
        raise FileExistsError(errno.EEXIST, "the destination file already exists", name)
    return False


def sync_folder(fd: int) -> None:
    """Flush a folder's entries to disk, where the filesystem can."""
    try:
        os.fsync(fd)
    except OSError as error:
        if error.errno not in _NO_FOLDER_SYNC:
            raise


def write_replacing(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` through a private staging file renamed over it.

    The folder is resolved but the name is not, so a link at ``path`` is replaced or refused,
    never written through. UnsafePathError if ``path`` exists and is not a regular file.
    """
    folder, name = path.parent.resolve(), path.name
    folder_fd = os.open(folder, FOLDER_FLAGS)
    try:
        staging = f".{name}.{secrets.token_hex(TOKEN_BYTES)}{STAGING_SUFFIX}"
        fd = os.open(staging, CREATE_FLAGS, PRIVATE_MODE, dir_fd=folder_fd)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            _require_replaceable(folder_fd, name, path)
            os.replace(staging, name, src_dir_fd=folder_fd, dst_dir_fd=folder_fd)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(staging, dir_fd=folder_fd)
            raise
        sync_folder(folder_fd)
    finally:
        os.close(folder_fd)


def _require_replaceable(folder_fd: int, name: str, path: Path) -> None:
    try:
        info = os.stat(name, dir_fd=folder_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if not stat.S_ISREG(info.st_mode):
        raise UnsafePathError(f"{path} is a link or not a regular file; not writing to it")
