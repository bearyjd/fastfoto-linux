"""Where the plan file is written: the folder is opened once, and the write goes through it.

``check`` can run for hours between choosing the plan path and writing the plan. The plan's
folder is therefore opened when ``check`` starts (from ``/`` down, never through a link, and not
inside the library), and the plan is published through that descriptor: a new file is linked into
place (which never replaces anything), and an older plan is renamed over only if what is there
now is still a plan.
"""

import contextlib
import os
import secrets
import stat
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from fastfoto_linux.library import confine, fdio
from fastfoto_linux.library.plan_format import PLAN_COLUMNS
from fastfoto_linux.library.safety import UnsafePathError

MAX_HEADER_CHARS = 1024
INSTALL_ATTEMPTS = 3  # something else may appear at the name between looking and publishing
HEADER = ",".join(PLAN_COLUMNS)


@dataclass(frozen=True)
class PlanTarget:
    """The plan's open folder and the file name in it; ``shown`` is the path for messages."""

    folder_fd: int
    name: str
    shown: Path


def _is_plan_file(folder_fd: int, name: str) -> bool:
    """Whether the regular file ``name`` starts with the plan's header line."""
    try:
        fd = os.open(name, fdio.READ_FLAGS, dir_fd=folder_fd)
    except OSError:
        return False
    with os.fdopen(fd, encoding="utf-8", errors="replace") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            return False
        return handle.readline(MAX_HEADER_CHARS).rstrip("\r\n") == HEADER


def _is_replaceable(target: PlanTarget) -> bool:
    """True for an older plan, False for no file; UnsafePathError for anything else there."""
    try:
        info = os.stat(target.name, dir_fd=target.folder_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(info.st_mode):
        raise UnsafePathError(f"{target.shown} is a link; not writing through it")
    if not stat.S_ISREG(info.st_mode) or not _is_plan_file(target.folder_fd, target.name):
        raise UnsafePathError(f"{target.shown} exists and is not a plan file; not overwriting it")
    return True


@contextlib.contextmanager
def open_plan_target(plan: Path, library: os.stat_result | None = None) -> Iterator[PlanTarget]:
    """Open the plan's folder and check what is at the plan path; UnsafePathError if unsafe.

    Refused: a folder that is (or lies below) the library, a link or special file at the path,
    and an existing file that is not a plan. The descriptor is closed when the block ends.
    """
    if plan.name in ("", ".", ".."):
        raise UnsafePathError(f"{plan} is not a file name")
    try:
        folder_fd = confine.open_folder(plan.parent.resolve())
    except FileNotFoundError:
        raise UnsafePathError(f"the folder for the plan file {plan} does not exist") from None
    try:
        target = PlanTarget(folder_fd, plan.name, plan)
        _check_new_target(target, library)
        yield target
    finally:
        os.close(folder_fd)


def _check_new_target(target: PlanTarget, library: os.stat_result | None) -> None:
    if library is not None:
        try:
            confine.refuse_inside(target.folder_fd, library)
        except UnsafePathError:
            raise UnsafePathError(
                f"the plan file {target.shown} would be inside the library"
            ) from None
    _is_replaceable(target)


def publish_plan(target: PlanTarget, data: bytes) -> None:
    """Write ``data`` as the plan; nothing but an older plan is ever replaced."""
    staging = f".{target.name}.{secrets.token_hex(fdio.TOKEN_BYTES)}{fdio.STAGING_SUFFIX}"
    fd = os.open(staging, fdio.CREATE_FLAGS, fdio.PRIVATE_MODE, dir_fd=target.folder_fd)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        _install(target, staging, data)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(staging, dir_fd=target.folder_fd)
    fdio.sync_folder(target.folder_fd)


def _install(target: PlanTarget, staging: str, data: bytes) -> None:
    for _ in range(INSTALL_ATTEMPTS):
        if _is_replaceable(target):
            os.replace(
                staging, target.name, src_dir_fd=target.folder_fd, dst_dir_fd=target.folder_fd
            )
            return
        try:
            fdio.link_new(target.folder_fd, staging, target.name, data)
        except FileExistsError:
            continue  # something appeared meanwhile: look at it again
        return
    raise UnsafePathError(
        f"{target.shown} keeps changing while the plan is written; not writing it"
    )
