"""Opening folders one step at a time without following links, and keeping them out of the library.

A folder that was checked as a path can be swapped for a link, or for a different folder, before it
is written to. So the folder is opened once, from ``/`` down, one name at a time and never through
a link; the open descriptor is what everything is then written through, and the folders above it
are compared, by device and inode, with the library.
"""

import errno
import os
import stat
from pathlib import Path

from fastfoto_linux.library.safety import UnsafePathError, same_directory

# Intermediate folders only need to be passed through, which does not take read permission.
STEP_FLAGS = getattr(os, "O_PATH", os.O_RDONLY) | os.O_DIRECTORY | os.O_CLOEXEC
FOLDER_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
PERMISSION_BITS = 0o777
MAX_DEPTH = 4096  # more levels than any path can have: ``..`` always ends at the root before this
# What opening a link or a plain file as a folder (without following links) reports.
_NOT_A_FOLDER = frozenset({errno.ELOOP, errno.ENOTDIR})
# Filesystems without Unix permissions refuse chmod; the folder keeps its default mode.
_NO_MODES = frozenset({errno.EPERM, errno.ENOTSUP})


def _open_below(parent_fd: int, name: str, flags: int) -> int:
    try:
        return os.open(name, flags | os.O_NOFOLLOW, dir_fd=parent_fd)
    except OSError as error:
        if error.errno in _NOT_A_FOLDER:
            raise UnsafePathError(f"{name!r} is a link or not a folder; not using it") from error
        raise


def _make_below(parent_fd: int, name: str, mode: int | None) -> int:
    """The folder ``name`` below ``parent_fd``, made now if missing (and given ``mode`` if new)."""
    created = True
    try:
        os.mkdir(name, dir_fd=parent_fd)
    except FileExistsError:
        created = False
    fd = _open_below(parent_fd, name, FOLDER_FLAGS)
    if created and mode is not None:
        try:
            os.fchmod(fd, mode & PERMISSION_BITS)
        except OSError as error:
            if error.errno not in _NO_MODES:
                os.close(fd)
                raise
    return fd


def _step(parent_fd: int, name: str, *, last: bool, create: bool, mode: int | None) -> int:
    flags = FOLDER_FLAGS if last else STEP_FLAGS
    try:
        return _open_below(parent_fd, name, flags)
    except FileNotFoundError:
        if not create:
            raise
    return _make_below(parent_fd, name, mode if last else None)


def open_folder(path: Path, *, create: bool = False, last_mode: int | None = None) -> int:
    """A descriptor for the folder at ``path``, opened from ``/`` without following any link.

    ``path`` should already be resolved: a link anywhere on it is refused (UnsafePathError), not
    followed. Missing folders are made when ``create`` is true; the last one, if it is new, gets
    ``last_mode``. FileNotFoundError when a folder is missing and ``create`` is false.
    """
    parts = Path(os.path.abspath(path)).parts
    fd = os.open(parts[0], FOLDER_FLAGS)
    try:
        for index, name in enumerate(parts[1:], start=1):
            last = index == len(parts) - 1
            child = _step(fd, name, last=last, create=create, mode=last_mode)
            os.close(fd)
            fd = child
    except BaseException:
        os.close(fd)
        raise
    return fd


def refuse_inside(fd: int, library: os.stat_result) -> None:
    """UnsafePathError if the folder ``fd`` is the library or lies anywhere below it.

    Every level above ``fd`` is reached through ``..`` and compared by device and inode, so two
    spellings of one folder (bind mounts, case-folding filesystems) are told apart from names.
    """
    current, info = fd, os.fstat(fd)
    opened: list[int] = []
    try:
        for _ in range(MAX_DEPTH):
            if same_directory(info, library):
                raise UnsafePathError("refusing to write: the folder is the library or inside it")
            current = os.open("..", STEP_FLAGS, dir_fd=current)
            opened.append(current)
            above = os.fstat(current)
            if not stat.S_ISDIR(above.st_mode) or same_directory(above, info):
                return  # the root is its own parent
            info = above
            if len(opened) > 1:
                os.close(opened.pop(0))
        raise UnsafePathError("the folder is nested too deeply to be checked")
    finally:
        for leftover in opened:
            os.close(leftover)
