"""File access through open descriptors, so a path swapped mid-run is never followed.

Reading opens the file once without following a link, checks the open file is a regular one and
reads from that descriptor. Writing opens the destination folder from ``/`` down (see ``confine``),
then every folder below it one step at a time with ``dir_fd`` and ``O_NOFOLLOW``, so a folder
replaced by a link between the checks and the write is refused instead of followed. A new file is
written under a private staging name and published with ``link`` (which never replaces) while it
is still private; only then does it get the source's mode and times, through the open descriptor.
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

from fastfoto_linux.library import confine, safety
from fastfoto_linux.library.safety import UnsafePathError

logger = logging.getLogger(__name__)

MAX_FILE_BYTES = 128 * 1024 * 1024  # a photo larger than this is skipped, never read into memory
READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
FOLDER_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
CREATE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
PRIVATE_MODE = 0o600
PERMISSION_BITS = 0o777  # leaves out setuid, setgid and the sticky bit
OWNER_RWX = 0o700  # a folder we create must stay writable for us, whatever the source's mode
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
    folder_modes: tuple[int, ...] = ()  # the modes of the folders above it, outermost first


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
        for depth, part in enumerate(pure.parent.parts):
            modes = source.folder_modes
            folder_fd = _enter_folder(folder_fd, part, modes[depth] if depth < len(modes) else None)
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
            os.fsync(handle.fileno())
            written = link_new(folder_fd, staging, name, content)
            if written:
                _finish_published(handle.fileno(), folder_fd, name, source)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(staging, dir_fd=folder_fd)
    if written:
        sync_folder(folder_fd)
    return written


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


def link_new(folder_fd: int, staging: str, name: str, content: bytes) -> bool:
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
        if not _is_placeholder(folder_fd, name):
            return _already_there(folder_fd, name, content)
    try:
        os.rename(staging, name, src_dir_fd=folder_fd, dst_dir_fd=folder_fd)
    except BaseException:
        os.unlink(name, dir_fd=folder_fd)
        raise
    return True


def _is_placeholder(folder_fd: int, name: str) -> bool:
    """Whether ``name`` is an empty regular file: what a crash after the claim leaves behind."""
    try:
        info = os.stat(name, dir_fd=folder_fd, follow_symlinks=False)
    except OSError:
        return False
    return stat.S_ISREG(info.st_mode) and info.st_size == 0


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
