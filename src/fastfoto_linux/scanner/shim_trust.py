"""Which USB gap shim may be preloaded into scanimage: who owns it and who can change it.

The shim is loaded into ``scanimage``, so whoever can change the file, or a folder it sits in,
can run code as this user. A shim is used only when it and every folder above it (of the path as
given and of the path it resolves to) belong to this user or to root, and nobody else can write
to them: not "others" (a sticky ``/tmp`` included), and a group only when it is the user's own
private group, which has no other members besides the user.

A POSIX access list can grant write to one more user or group without the mode bits showing it
(``setfacl -m u:nobody:rwx`` raises the group bits to the mask, which a private group passes), so
the list is read too: a named user other than this one or root, or a named group other than the
private one, must not be able to write, after the mask has cut down what its entry grants.

Inside a Flatpak sandbox the files of a system-wide install belong to root on the host, which the
sandbox shows as the overflow uid (nobody). So that the shim the Flatpak ships can be used there,
that one owner is accepted for what is under ``/app``, but only when ``/app`` is a read-only mount
(nothing in the sandbox can have changed it). Every other check still applies.
"""

import errno
import grp
import logging
import os
import pwd
import stat
import struct
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_TRUST_ROOT = Path("/")
SHIM_TRUST_ROOT = DEFAULT_TRUST_ROOT  # the walk up the folders ends here (tests move it)
ROOT_UID = 0
FLATPAK_INFO = Path("/.flatpak-info")  # exists only inside a Flatpak sandbox
FLATPAK_APP_ROOT = Path("/app")  # where a Flatpak mounts the application, read-only
OVERFLOW_UID = 65534  # how a file owned by another host user (root) looks inside the sandbox
OVERFLOW_UID_FILE = Path("/proc/sys/kernel/overflowuid")
FALLBACK_OVERFLOW_UID = 65534

ACL_XATTR = "system.posix_acl_access"
ACL_VERSION = 2
ACL_HEADER = struct.Struct("<I")  # the version
ACL_ENTRY = struct.Struct("<HHI")  # tag, permissions, user or group id
ACL_USER, ACL_GROUP, ACL_MASK = 0x02, 0x08, 0x10  # the tags of named users and groups, the mask
ACL_WRITE = 0o2
ACL_ALL = 0o7
NO_ACL_ERRORS = frozenset({errno.ENODATA, errno.ENOTSUP})  # no list, or a file system with none


def overflow_uid() -> int:
    raise NotImplementedError


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
    if info.st_uid not in (os.geteuid(), ROOT_UID) and not _flatpak_app_owner(path, info.st_uid):
        return f"{what} {path} is owned by uid {info.st_uid}; it must belong to you or to root"
    if stat.S_ISLNK(info.st_mode):
        return None  # a link's own mode bits mean nothing (/home is one); its target is checked
    if info.st_mode & stat.S_IWOTH:
        return f"{what} {path} is writable by everyone; run chmod o-w {path}"
    if info.st_mode & stat.S_IWGRP and not _private_group(info.st_gid):
        return (
            f"{what} {path} is writable by group '{_group_name(info.st_gid)}'; run chmod g-w {path}"
        )
    return _acl_problem(path, what)


def _flatpak_app_owner(path: Path, uid: int) -> bool:
    """True when ``uid`` is the host's root as a Flatpak sandbox shows it for a file of ``/app``.

    All must hold: this is a Flatpak sandbox, the path is ``/app`` or under it, and the mount it is
    on is read-only. A folder next to ``/app``, a link out of it, or a writable ``/app`` gets no
    exception, and neither does any other owner.
    """
    return (
        uid == OVERFLOW_UID
        and FLATPAK_INFO.exists()
        and path.is_relative_to(FLATPAK_APP_ROOT)
        and bool(os.statvfs(path).f_flag & os.ST_RDONLY)
    )


def _acl_problem(path: Path, what: str) -> str | None:
    """Why the access list of ``path`` lets someone else write (None: it does not, or is none)."""
    try:
        blob = os.getxattr(path, ACL_XATTR, follow_symlinks=False)
    except OSError as error:
        if error.errno in NO_ACL_ERRORS:
            return None
        raise
    entries = _acl_entries(blob)
    if entries is None:
        return f"{what} {path} has an access list that cannot be read"
    mask = next((perms for tag, perms, _ in entries if tag == ACL_MASK), ACL_ALL)
    for tag, perms, who in entries:
        if not perms & mask & ACL_WRITE:
            continue
        if tag == ACL_USER and who not in (os.geteuid(), ROOT_UID):
            return _acl_refusal(what, path, f"user {who}", f"u:{who}")
        if tag == ACL_GROUP and not _private_group(who):
            return _acl_refusal(what, path, f"group {who}", f"g:{who}")
    return None


def _acl_refusal(what: str, path: Path, who: str, entry: str) -> str:
    return f"{what} {path} has an access list that lets {who} write; run setfacl -x {entry} {path}"


def _acl_entries(blob: bytes) -> list[tuple[int, int, int]] | None:
    """The (tag, permissions, id) of each entry of a version 2 list; None for anything else."""
    start = ACL_HEADER.size
    if len(blob) < start or (len(blob) - start) % ACL_ENTRY.size:
        return None
    if ACL_HEADER.unpack_from(blob)[0] != ACL_VERSION:
        return None
    return [ACL_ENTRY.unpack_from(blob, at) for at in range(start, len(blob), ACL_ENTRY.size)]


def _private_group(gid: int) -> bool:
    """True for the user's own group when nobody but the user is in it (a user-private group)."""
    if gid != os.getegid():
        return False
    try:
        members = grp.getgrgid(gid).gr_mem
        return not members or set(members) == {pwd.getpwuid(os.geteuid()).pw_name}
    except KeyError:
        return False


def _group_name(gid: int) -> str:
    try:
        return grp.getgrgid(gid).gr_name
    except KeyError:
        return str(gid)
