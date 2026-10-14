"""Write new files without ever overwriting, all-or-nothing, and survive a crash.

Every file is written under a hidden staging name (``.<name>.<token>.tmp``) in its own folder,
flushed to disk, then published under its final name without replacing anything. A crash or
SIGKILL part-way can leave such a ``.tmp`` file behind; numbering ignores them and nothing
sweeps them, so they can simply be deleted.
"""

import errno
import fcntl
import logging
import os
import secrets
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from fastfoto_linux.output.errors import OutputCollisionError

logger = logging.getLogger(__name__)

LOCK_NAME = ".fastfoto-linux.lock"
LOCK_FILE_MODE = 0o666  # before the umask
TEMP_SUFFIX = ".tmp"
TEMP_TOKEN_BYTES = 4
# link() errors that mean "this filesystem has no hard links" (FAT/exFAT, some network mounts).
_NO_HARD_LINKS = frozenset({errno.EPERM, errno.ENOTSUP, errno.ENOSYS})
# flock() errors that mean "this filesystem has no usable file locks".
_NO_LOCKS = frozenset({errno.ENOLCK, errno.ENOTSUP, errno.ENOSYS, errno.EINVAL})

_FileId = tuple[int, int]


@dataclass
class _Staged:
    """A file being written: its staging and final names, and the identity of every file this
    call created for ``target``, so rollback can tell its own file from someone else's."""

    temp: Path
    target: Path
    ours: set[_FileId]


def write_new_files(items: Sequence[tuple[Path, bytes]]) -> None:
    """Write every ``(path, data)`` pair as a new file, or none of them.

    Data is flushed to disk before a file is published, and each folder is synced once all
    files are in place, so a power cut cannot leave a truncated file under its final name.
    An existing file raises OutputCollisionError and is never touched. If anything fails,
    including an interrupt, the files this call created and every staging file are removed.
    """
    staged: list[_Staged] = []
    try:
        for target, data in items:
            staged.append(_stage(target, data))
        for entry in staged:
            _publish(entry)
    except BaseException:
        _rollback(staged)
        raise
    _sync_folders({entry.target.parent for entry in staged})


def _file_id(info: os.stat_result) -> _FileId:
    return (info.st_dev, info.st_ino)


def _stage(target: Path, data: bytes) -> _Staged:
    token = secrets.token_hex(TEMP_TOKEN_BYTES)
    temp = target.with_name(f".{target.name}.{token}{TEMP_SUFFIX}")
    try:
        with temp.open("xb") as handle:
            file_id = _file_id(os.fstat(handle.fileno()))
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        _discard([temp])
        raise
    return _Staged(temp=temp, target=target, ours={file_id})


def _publish(entry: _Staged) -> None:
    try:
        os.link(entry.temp, entry.target, follow_symlinks=False)
    except FileExistsError as exc:
        raise _collision(entry.target) from exc
    except OSError as exc:
        if exc.errno not in _NO_HARD_LINKS:
            raise
        _reserve_then_replace(entry)
        return
    entry.temp.unlink()


def _reserve_then_replace(entry: _Staged) -> None:
    """Fallback for filesystems without hard links: claim the name exclusively, then swap."""
    try:
        with entry.target.open("xb") as handle:
            entry.ours.add(_file_id(os.fstat(handle.fileno())))
    except FileExistsError as exc:
        raise _collision(entry.target) from exc
    os.replace(entry.temp, entry.target)


def _collision(target: Path) -> OutputCollisionError:
    return OutputCollisionError(f"{target} already exists; refusing to overwrite it")


def _rollback(staged: Iterable[_Staged]) -> None:
    for entry in staged:
        _remove_if_ours(entry)
        _discard([entry.temp])


def _remove_if_ours(entry: _Staged) -> None:
    """Remove ``target`` only if it is a file this call created, never one that merely has
    the same name, even if an interrupt landed before the call noted it down."""
    try:
        found = _file_id(entry.target.lstat())
    except FileNotFoundError:
        return
    except OSError:
        logger.warning("could not inspect %s while cleaning up", entry.target, exc_info=True)
        return
    if found in entry.ours:
        _discard([entry.target])


def _discard(paths: Iterable[Path]) -> None:
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("could not remove %s while cleaning up", path, exc_info=True)


def _sync_folders(folders: Iterable[Path]) -> None:
    """Flush folder entries so the new names survive a power cut.

    The files are already complete and in place, so a folder that cannot be synced (some
    network and FUSE filesystems) is logged, not treated as a failure.
    """
    for folder in folders:
        try:
            fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            logger.warning("could not sync folder %s", folder, exc_info=True)


@contextmanager
def locked_folder(directory: Path) -> Iterator[None]:
    """Hold an exclusive lock on ``directory`` while numbering and publishing a photo.

    Writers (threads or processes) serialise on a ``LOCK_NAME`` file kept in the folder; it is
    never deleted, because removing a lock file others may be waiting on breaks the lock.
    Filesystems without locks are tolerated with a warning, as the retry on collision in the
    writer still protects against two writers choosing the same file.
    """
    fd = os.open(directory / LOCK_NAME, os.O_RDWR | os.O_CREAT, LOCK_FILE_MODE)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
        except OSError as exc:
            if exc.errno not in _NO_LOCKS:
                raise
            logger.warning("%s does not support file locks; writers are not serialised", directory)
        yield
    finally:
        os.close(fd)
