"""Which USB gap shim may be preloaded into scanimage: who owns it and who can change it.

The shim is loaded into ``scanimage``, so whoever can change the file, or a folder it sits in,
can run code as this user. A shim is used only when it and every folder above it (of the path as
given and of the path it resolves to) belong to this user or to root, and nobody else can write
to them: not "others" (a sticky ``/tmp`` included), and a group only when it is the user's own
private group, which has no other members.
"""

import errno
import grp
import logging
import os
import stat
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_TRUST_ROOT = Path("/")
SHIM_TRUST_ROOT = DEFAULT_TRUST_ROOT  # the walk up the folders ends here (tests move it)
ROOT_UID = 0


@dataclass(frozen=True)
class ShimChoice:
    """The shim to use (None when no candidate is usable) and why the others were refused."""

    path: Path | None
    refused: tuple[str, ...] = ()


def select_shim(candidates: Sequence[Path]) -> ShimChoice:
    """The first candidate that exists and is safe to load, and why the others were refused.

    A candidate that is not there (or vanishes while it is looked at) is simply not found.
    """
    refused: list[str] = []
    for candidate in candidates:
        try:
            resolved, problem = _examine(candidate)
        except (FileNotFoundError, NotADirectoryError):
            continue
        except OSError as error:
            problem = f"{candidate} cannot be examined: {error.strerror or error}"
            resolved = candidate
        if problem is None:
            return ShimChoice(resolved, tuple(refused))
        logger.warning("not using the shim: %s", problem)
        refused.append(problem)
    return ShimChoice(None, tuple(refused))


def _examine(candidate: Path) -> tuple[Path, str | None]:
    """The resolved path and the first reason not to load it (None: fine)."""
    given = Path(os.path.abspath(candidate))
    try:
        resolved = Path(os.path.realpath(given, strict=True))
    except OSError as error:
        if error.errno == errno.ELOOP:
            return given, f"{given} is a link that leads back to itself"
        raise
    if not stat.S_ISREG(os.lstat(resolved).st_mode):
        raise FileNotFoundError(str(resolved))
    for path in (given, resolved):
        for step in _chain(path):
            problem = _entry_problem(step, is_shim=step == path)
            if problem is not None:
                return resolved, problem
    return resolved, None


def _chain(path: Path) -> list[Path]:
    """``path`` and its folders, nearest first, up to and including the trust root."""
    chain = [path]
    for parent in path.parents:
        chain.append(parent)
        if parent == SHIM_TRUST_ROOT:
            break
    return chain


def _entry_problem(path: Path, *, is_shim: bool) -> str | None:
    info = os.lstat(path)
    what = "the shim" if is_shim else "folder"
    if info.st_uid not in (os.geteuid(), ROOT_UID):
        return f"{what} {path} is owned by uid {info.st_uid}; it must belong to you or to root"
    if stat.S_ISLNK(info.st_mode):
        return None  # a link's own mode bits mean nothing (/home is one); its target is checked
    if info.st_mode & stat.S_IWOTH:
        return f"{what} {path} is writable by everyone; run chmod o-w {path}"
    if info.st_mode & stat.S_IWGRP and not _private_group(info.st_gid):
        return (
            f"{what} {path} is writable by group '{_group_name(info.st_gid)}'; run chmod g-w {path}"
        )
    return None


def _private_group(gid: int) -> bool:
    """True for the user's own group when nobody else is in it (a user-private group)."""
    if gid != os.getegid():
        return False
    try:
        return not grp.getgrgid(gid).gr_mem
    except KeyError:
        return False


def _group_name(gid: int) -> str:
    try:
        return grp.getgrgid(gid).gr_name
    except KeyError:
        return str(gid)
