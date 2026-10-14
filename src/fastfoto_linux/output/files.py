"""Write new files without ever overwriting, all-or-nothing, and survive a crash.

Every file is written under a hidden staging name (``.<name>.<token>.tmp``) in its own folder,
flushed to disk, then published under its final name without replacing anything. A crash or
SIGKILL part-way can leave such a ``.tmp`` file behind; numbering ignores them and nothing
sweeps them, so they can simply be deleted.

On filesystems without hard links (FAT/exFAT, some network mounts) a file is published by
creating its final name exclusively and swapping the finished file over it. A SIGKILL or power
cut in that short window can leave a zero-length file under the final name; the data itself is
never half-written under a name that held a complete file.
"""

import errno
import fcntl
import logging
import os
import secrets
import time
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from fastfoto_linux.output.errors import OutputCollisionError, OutputLockTimeoutError

logger = logging.getLogger(__name__)

LOCK_NAME = ".fastfoto-linux.lock"
LOCK_FILE_MODE = 0o666  # before the umask
LOCK_TIMEOUT_S = 60.0
LOCK_POLL_S = 0.05
TEMP_SUFFIX = ".tmp"
TEMP_TOKEN_BYTES = 4
# link() errors that mean "this filesystem has no hard links" (FAT/exFAT, some network mounts).
_NO_HARD_LINKS = frozenset({errno.EPERM, errno.ENOTSUP, errno.ENOSYS})
# flock() errors that mean "this filesystem has no usable file locks".
_NO_LOCKS = frozenset({errno.ENOLCK, errno.ENOTSUP, errno.ENOSYS, errno.EINVAL})
# Opening the lock file is refused, e.g. a 0644 lock left by another user in a shared folder.
_LOCK_OPEN_DENIED = frozenset({errno.EACCES, errno.EPERM})
# fsync() on a folder is not supported on every filesystem; that is not a failure.
_NO_FOLDER_SYNC = frozenset({errno.EINVAL, errno.ENOTSUP, errno.ENOSYS})

_FileId = tuple[int, int]


@dataclass
class _Staged:
    """A file being written: its staging and final names, and the identity of every file this
    call created for ``target``, so rollback can tell its own file from someone else's."""

    temp: Path
    target: Path
    ours: set[_FileId]
    # Inode numbers alone are not trusted (some filesystems repeat or fake them): rollback acts
    # only on a name it actually tried to create (``attempted``) and did not find taken
    # (``collided``).
    attempted: bool = False
    collided: bool = False


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
    sync_folders({entry.target.parent for entry in staged})


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
    entry.attempted = True  # before the call, so an interrupt inside it is still cleaned up
    try:
        os.link(entry.temp, entry.target, follow_symlinks=False)
    except FileExistsError as exc:
        raise _collision(entry) from exc
    except OSError as exc:
        if exc.errno not in _NO_HARD_LINKS:
            raise
        _reserve_then_replace(entry)
        return
    entry.temp.unlink()


def _reserve_then_replace(entry: _Staged) -> None:
    """Fallback for filesystems without hard links: claim the name exclusively, then swap."""
    try:
        handle = entry.target.open("xb")
    except FileExistsError as exc:
        raise _collision(entry) from exc
    with handle:
        entry.ours.add(_file_id(os.fstat(handle.fileno())))
    os.replace(entry.temp, entry.target)


def _collision(entry: _Staged) -> OutputCollisionError:
    entry.collided = True
    return OutputCollisionError(f"{entry.target} already exists; refusing to overwrite it")


def _rollback(staged: Iterable[_Staged]) -> None:
    for entry in staged:
        _remove_if_ours(entry)
        _discard([entry.temp])


def _remove_if_ours(entry: _Staged) -> None:
    """Remove ``target`` only if this call created it: never a name it found already taken,
    never one it did not get to, and never a file that merely has the same name, even if an
    interrupt landed before the call noted its own file down."""
    if not entry.attempted or entry.collided:
        return
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


def sync_folders(folders: Iterable[Path]) -> None:
    """Flush folder entries so the new names survive a power cut.

    The files are already complete and in place, so a folder that cannot be synced because the
    filesystem does not support it is fine, and other problems are logged. An I/O error (EIO)
    means the data may not have reached the disk and is raised, though the files stay.
    """
    for folder in folders:
        try:
            fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError as exc:
            if exc.errno == errno.EIO:
                raise
            if exc.errno in _NO_FOLDER_SYNC:
                logger.debug("folder %s does not support fsync", folder)
            else:
                logger.warning("could not sync folder %s", folder, exc_info=True)


def _open_lock(directory: Path) -> int | None:
    """Open (creating if needed) the lock file; None if this user may not open it."""
    flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW
    try:
        return os.open(directory / LOCK_NAME, flags, LOCK_FILE_MODE)
    except OSError as exc:
        if exc.errno not in _LOCK_OPEN_DENIED:
            raise
        logger.warning(
            "cannot open %s in %s (%s); writers are not serialised", LOCK_NAME, directory, exc
        )
        return None


def _acquire_lock(fd: int, directory: Path) -> bool:
    """Take the exclusive lock, polling until LOCK_TIMEOUT_S; False if locks are unsupported."""
    deadline = time.monotonic() + LOCK_TIMEOUT_S
    announced = False
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            pass
        except OSError as exc:
            if exc.errno not in _NO_LOCKS:
                raise
            logger.warning("%s does not support file locks; writers are not serialised", directory)
            return False
        else:
            return True
        if time.monotonic() >= deadline:
            raise OutputLockTimeoutError(
                f"{directory} is locked by another writer; gave up after {LOCK_TIMEOUT_S:g} s"
            )
        if not announced:
            logger.info("waiting for another writer to finish with %s", directory)
            announced = True
        time.sleep(LOCK_POLL_S)


@contextmanager
def locked_folder(directory: Path) -> Iterator[None]:
    """Hold an exclusive lock on ``directory`` while numbering and publishing a photo.

    Writers (threads or processes) serialise on a ``LOCK_NAME`` file kept in the folder; it is
    never deleted, because removing a lock file others may be waiting on breaks the lock. A
    holder that does not let go within ``LOCK_TIMEOUT_S`` makes the wait fail with
    OutputLockTimeoutError. Filesystems without locks, or a lock file this user cannot open,
    are tolerated with a warning: the writer then runs unserialised, and the retry on
    collision in the writer only protects against overwriting the same file.
    """
    fd = _open_lock(directory)
    locked = False
    try:
        if fd is not None:
            locked = _acquire_lock(fd, directory)
        yield
    finally:
        if fd is not None:
            try:
                if locked:
                    fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)
