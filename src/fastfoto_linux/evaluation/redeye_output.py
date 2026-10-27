"""Where results go: outside the repo, atomically, with private permissions."""

import contextlib
import errno
import fcntl
import os
import time
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path

from fastfoto_linux.evaluation.redeye_images import ImageError, read_regular_fd
from fastfoto_linux.evaluation.redeye_manifest import Manifest, ManifestError

PROJECT_NAME = "fastfoto-linux"
MAX_PYPROJECT_BYTES = 1_000_000
DIR_MODE = 0o700
FILE_MODE = 0o600
LOCK_NAME = ".write.lock"
LOCK_WAIT_SECONDS = 5.0
LOCK_POLL_SECONDS = 0.05
_DIR_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0)


def _is_project_checkout(directory: Path) -> bool:
    if not (directory / ".git").exists():
        return False
    try:
        fd = os.open(directory / "pyproject.toml", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        data = read_regular_fd(fd, MAX_PYPROJECT_BYTES)  # a FIFO here must not block
        return tomllib.loads(data.decode()).get("project", {}).get("name") == PROJECT_NAME
    except (OSError, ValueError, ImageError):
        return False


def _default_out(manifest: Manifest, env: Mapping[str, str]) -> Path:
    cache = env.get("XDG_CACHE_HOME")
    if cache and not Path(cache).is_absolute():
        raise ManifestError("XDG_CACHE_HOME must be an absolute path")
    base = Path(cache) if cache else Path(env.get("HOME") or Path.home()) / ".cache"
    return base / "fastfoto-linux" / "redeye-eval" / manifest.sha256[:12]


def check_out_allowed(path: Path, forbidden: Sequence[Path]) -> None:
    """Refuse ``path`` inside (or equal to) a forbidden root or a fastfoto-linux checkout."""
    for root in forbidden:
        if root == path or root in path.parents:
            raise ManifestError("the output directory must be outside the manifest directory")
    if any(_is_project_checkout(d) for d in (path, *path.parents)):
        raise ManifestError("the output directory must be outside the fastfoto-linux checkout")


def resolve_out_dir(manifest: Manifest, out: Path | None, env: Mapping[str, str]) -> Path:
    """``out`` (or the cache default), refused inside the manifest root or the project checkout."""
    resolved = (out if out is not None else _default_out(manifest, env)).expanduser().resolve()
    check_out_allowed(resolved, [manifest.root])
    return resolved


def _temporary(name: str) -> str:
    return f".{name}.{os.getpid()}.tmp"


def _write_temporary(dir_fd: int, name: str, text: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(_temporary(name), flags, FILE_MODE, dir_fd=dir_fd)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)


def _verify_dir(fd: int, forbidden: Sequence[Path]) -> None:
    """``fd`` is still a linked directory that is neither a forbidden root, inside one, nor inside
    a checkout, whatever happened to its path since. One syscall can still pass between this
    check and the use of ``fd``."""
    identity = os.fstat(fd)
    if identity.st_nlink == 0:
        raise ManifestError("the output directory was removed while writing")
    for root in forbidden:
        try:
            info = os.stat(root)
        except OSError:  # not created (yet): the path check below covers it
            continue
        if (info.st_dev, info.st_ino) == (identity.st_dev, identity.st_ino):
            raise ManifestError("the output directory must be outside the manifest directory")
    check_out_allowed(Path(os.readlink(f"/proc/self/fd/{fd}")), [r.resolve() for r in forbidden])


def _step(parent: int, part: str, forbidden: Sequence[Path], created: list) -> int:
    """An fd on ``part`` under ``parent`` (no symlink followed); a missing one is created,
    recorded in ``created`` and checked at once."""
    try:
        return os.open(part, _DIR_FLAGS, dir_fd=parent)
    except FileNotFoundError:
        pass
    except OSError as error:
        if error.errno in (errno.ELOOP, errno.ENOTDIR):
            raise ManifestError("the output directory is not a plain directory") from error
        raise
    os.mkdir(part, DIR_MODE, dir_fd=parent)
    created.append((parent, part))
    child = os.open(part, _DIR_FLAGS, dir_fd=parent)
    try:
        _verify_dir(child, forbidden)
    except BaseException:
        os.close(child)
        raise
    return child


def _open_out_dir(out_dir: Path, forbidden: Sequence[Path]) -> int:
    """An fd on the output directory, walked from ``/`` without following a symlink and checked
    now. Directories created on the way are checked as they appear; if anything is refused,
    exactly the ones this call created are removed again."""
    held: list[int] = []
    created: list[tuple[int, str]] = []
    try:
        held.append(os.open("/", _DIR_FLAGS))
        for part in Path(os.path.abspath(out_dir)).parts[1:]:
            held.append(_step(held[-1], part, forbidden, created))
        _verify_dir(held[-1], forbidden)
    except BaseException:
        for parent, name in reversed(created):
            with contextlib.suppress(OSError):
                os.rmdir(name, dir_fd=parent)
        for descriptor in held:
            os.close(descriptor)
        raise
    for descriptor in held[:-1]:
        os.close(descriptor)
    return held[-1]


def _acquire_lock(dir_fd: int) -> int:
    """An exclusive advisory flock on ``.write.lock`` in the directory, waiting at most
    ``LOCK_WAIT_SECONDS``; close the returned fd to release it."""
    flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    lock = os.open(LOCK_NAME, flags, FILE_MODE, dir_fd=dir_fd)
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    try:
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return lock
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise ManifestError("another run is writing to this output directory") from None
                time.sleep(LOCK_POLL_SECONDS)
    except BaseException:
        os.close(lock)
        raise


def _write_bundle(
    fd: int, files: Mapping[str, str], forbidden: Sequence[Path], stale: Sequence[str]
) -> None:
    """Temporary files first, then the replaces in a fixed order with ``report.json`` last (so a
    new report implies the rest is new too); containment is re-verified before every step."""
    order = [n for n in files if n != "report.json"] + [n for n in files if n == "report.json"]
    pending: list[str] = []
    try:
        for name in order:
            _verify_dir(fd, forbidden)
            pending.append(name)
            _write_temporary(fd, name, files[name])
        while pending:
            _verify_dir(fd, forbidden)
            name = pending[0]
            os.replace(_temporary(name), name, src_dir_fd=fd, dst_dir_fd=fd)
            pending.pop(0)
        for name in stale:
            _verify_dir(fd, forbidden)
            with contextlib.suppress(FileNotFoundError):
                os.unlink(name, dir_fd=fd)
    except BaseException:
        for name in pending:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(_temporary(name), dir_fd=fd)
        raise


def write_outputs(
    out_dir: Path,
    files: Mapping[str, str],
    forbidden: Sequence[Path] = (),
    stale: Sequence[str] = (),
) -> None:
    """Write the bundle atomically per file (tmp + replace, relative to an fd on the directory)
    with mode 0o600 into a 0o700 directory, serialized by a per-directory advisory lock; remove
    the ``stale`` names (outputs of an earlier run that this run does not produce)."""
    fd = _open_out_dir(out_dir, forbidden)
    try:
        _verify_dir(fd, forbidden)  # again, before the lock file is created
        lock = _acquire_lock(fd)
        try:
            _write_bundle(fd, files, forbidden, stale)
        finally:
            os.close(lock)
    finally:
        os.close(fd)
