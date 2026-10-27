"""Where results go: outside the repo, in a new directory per run, with private permissions."""

import contextlib
import errno
import os
import secrets
import tomllib
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from fastfoto_linux.evaluation.redeye_images import ImageError, fdopen_owned, read_regular_fd
from fastfoto_linux.evaluation.redeye_manifest import Manifest, ManifestError

PROJECT_NAME = "fastfoto-linux"
MAX_PYPROJECT_BYTES = 1_000_000
DIR_MODE = 0o700
FILE_MODE = 0o600
_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_DIR_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY | _CLOEXEC
_CREATE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | _CLOEXEC
_OUTSIDE_MANIFEST = "the output directory must be outside the manifest directory"
_OUTSIDE_CHECKOUT = "the output directory must be outside the fastfoto-linux checkout"
_UNVERIFIED = "cannot verify the output location"
_ABSENT = (errno.ENOENT, errno.ENOTDIR, errno.ELOOP)  # no such entry, or a symlink in its place
REPORT = "report.json"
REPORT_TEMP = ".report.tmp"  # the report is built here and published whole
RUN_NAME_TRIES = 3

Identity = tuple[int, int]  # (st_dev, st_ino): what a directory is, whatever it is called now


def _is_our_pyproject(data: bytes) -> bool:
    """``data`` is a pyproject.toml of this project; one that cannot be parsed is someone else's."""
    try:
        project = tomllib.loads(data.decode()).get("project")
    except (ValueError, RecursionError):  # TOMLDecodeError and UnicodeDecodeError are ValueErrors
        return False
    return isinstance(project, dict) and project.get("name") == PROJECT_NAME


def _fd_is_checkout(fd: int) -> bool:
    """The directory open on ``fd`` is a fastfoto-linux checkout (a ``.git`` and our pyproject).

    A missing or symlinked entry means no. A failure to look (EIO, EACCES, ...) is a
    ``ManifestError``: what cannot be seen cannot be called safe.
    """
    try:
        os.stat(".git", dir_fd=fd)
        file = os.open("pyproject.toml", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        data = read_regular_fd(file, MAX_PYPROJECT_BYTES)  # a FIFO here must not block
    except OSError as error:
        if error.errno in _ABSENT:
            return False
        raise ManifestError(_UNVERIFIED) from error
    except ImageError as error:
        if error.code == "unreadable":
            raise ManifestError(_UNVERIFIED) from error
        return False  # not a regular file, or too large to be ours
    return _is_our_pyproject(data)


def _is_project_checkout(directory: Path) -> bool:
    try:
        fd = os.open(directory, _DIR_FLAGS)
    except OSError:
        return False
    try:
        return _fd_is_checkout(fd)
    finally:
        os.close(fd)


def _default_out(manifest: Manifest, env: Mapping[str, str]) -> Path:
    cache = env.get("XDG_CACHE_HOME")
    if cache and not Path(cache).is_absolute():
        raise ManifestError("XDG_CACHE_HOME must be an absolute path")
    base = Path(cache) if cache else Path(env.get("HOME") or Path.home()) / ".cache"
    return base / "fastfoto-linux" / "redeye-eval" / manifest.sha256[:12]


def check_out_allowed(path: Path, forbidden: Sequence[Path]) -> None:
    """Refuse ``path`` inside (or equal to) a forbidden root or a fastfoto-linux checkout (an early,
    friendly check by name; ``write_outputs`` repeats it by identity)."""
    for root in forbidden:
        if root == path or root in path.parents:
            raise ManifestError(_OUTSIDE_MANIFEST)
    if any(_is_project_checkout(d) for d in (path, *path.parents)):
        raise ManifestError(_OUTSIDE_CHECKOUT)


def resolve_out_dir(manifest: Manifest, out: Path | None, env: Mapping[str, str]) -> Path:
    """``out`` (or the cache default), refused inside the manifest root or the project checkout."""
    resolved = (out if out is not None else _default_out(manifest, env)).expanduser().resolve()
    check_out_allowed(resolved, [manifest.root])
    return resolved


def _identities(forbidden: Sequence[Path | Identity]) -> frozenset[Identity]:
    """Identities of the forbidden roots; a ``Path`` is looked at now (a missing one cannot be
    a corpus), an ``Identity`` was taken from a descriptor held since the run began."""
    found: set[Identity] = set()
    for root in forbidden:
        if isinstance(root, tuple):
            found.add(root)
            continue
        try:
            info = os.stat(root)
        except OSError:
            continue
        found.add((info.st_dev, info.st_ino))
    return frozenset(found)


def _refuse_if_contained(fd: int, forbidden: frozenset[Identity]) -> None:
    """Ascend from the directory open on ``fd`` with ``openat("..")`` to ``/`` and refuse if it
    or any ancestor is a forbidden root (by identity, not name) or a checkout. A rename racing
    the instant after the last such check cannot be seen by user-space code."""
    current = os.dup(fd)
    try:
        info = os.fstat(current)
        if info.st_nlink == 0:
            raise ManifestError("the output directory was removed while writing")
        while True:
            here = (info.st_dev, info.st_ino)
            if here in forbidden:
                raise ManifestError(_OUTSIDE_MANIFEST)
            if _fd_is_checkout(current):
                raise ManifestError(_OUTSIDE_CHECKOUT)
            parent = os.open("..", _DIR_FLAGS, dir_fd=current)
            previous, current = current, parent  # one fd owned at a time: the finally closes it
            try:  # noqa: SIM105  (no allocation here; EINTR may follow a close that released it)
                os.close(previous)
            except OSError:
                pass
            info = os.fstat(current)
            if (info.st_dev, info.st_ino) == here:  # ".." of "/" is "/"
                return
    except OSError as error:
        raise ManifestError("cannot verify the output directory") from error
    finally:
        os.close(current)


def _step(parent: int, part: str, forbidden: frozenset[Identity], created: list) -> int:
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
        _refuse_if_contained(child, forbidden)
    except BaseException:
        os.close(child)
        raise
    return child


def _open_out_dir(out_dir: Path, forbidden: frozenset[Identity]) -> int:
    """An fd on the output directory, walked from ``/`` without following a symlink and checked
    now. Directories created on the way are checked as they appear; if anything is refused,
    exactly the ones this call created are removed again."""
    held: list[int] = []
    created: list[tuple[int, str]] = []
    try:
        held.append(os.open("/", _DIR_FLAGS))
        for part in Path(os.path.abspath(out_dir)).parts[1:]:
            held.append(_step(held[-1], part, forbidden, created))
        _refuse_if_contained(held[-1], forbidden)
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


def _new_run_dir(out_fd: int) -> tuple[str, int]:
    """Make ``run-<UTC time>-<8 hex>`` under the output directory (``mkdir`` fails if it exists,
    and a taken name is retried with a new token) and open it."""
    for _ in range(RUN_NAME_TRIES):
        name = f"run-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{secrets.token_hex(4)}"
        try:
            os.mkdir(name, DIR_MODE, dir_fd=out_fd)
        except FileExistsError:
            continue
        try:
            return name, os.open(name, _DIR_FLAGS, dir_fd=out_fd)
        except BaseException:
            os.rmdir(name, dir_fd=out_fd)
            raise
    raise ManifestError("cannot choose a new run directory name")


def _write_file(run_fd: int, name: str, text: str, created: list[str]) -> None:
    """Create ``name`` in the run directory (exclusively, no symlink, mode 0o600), fill it and
    flush it to storage."""
    fd = os.open(name, _CREATE_FLAGS, FILE_MODE, dir_fd=run_fd)
    created.append(name)
    with fdopen_owned(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())


def _publish_report(run_fd: int, created: list[str]) -> None:
    """Give the finished temp file its name by atomic rename. Rename replaces, so a present
    ``report.json`` is refused first (the run directory is ours alone, made for this run)."""
    try:
        os.stat(REPORT, dir_fd=run_fd, follow_symlinks=False)
    except FileNotFoundError:
        pass
    except OSError as error:
        raise ManifestError("cannot write the results directory") from error
    else:
        raise ManifestError("report.json already exists in the run directory")
    os.rename(REPORT_TEMP, REPORT, src_dir_fd=run_fd, dst_dir_fd=run_fd)
    created.append(REPORT)
    os.fsync(run_fd)


def _discard(out_fd: int, run_name: str, run_fd: int, created: Sequence[str]) -> None:
    """Remove exactly what this call made: its files and then its run directory."""
    for name in created:
        with contextlib.suppress(OSError):
            os.unlink(name, dir_fd=run_fd)
    with contextlib.suppress(OSError):
        os.rmdir(run_name, dir_fd=out_fd)


def write_outputs(
    out_dir: Path, files: Mapping[str, str], forbidden: Sequence[Path | Identity] = ()
) -> str:
    """Write the bundle into a new ``run-...`` directory under ``out_dir`` and return its name.

    Nothing existing is touched. ``report.json`` is written whole to ``.report.tmp``, synced and
    only then renamed into place, so a ``report.json`` that exists is complete (barring storage
    that lies) and a run directory without it is incomplete. Containment (not a forbidden root,
    not inside one, not in a checkout) is checked by identity before the run directory is made
    and again after the last file, before the report is published; if the check or any write
    fails, the files and the directory this call made are removed. Every failure is a
    ``ManifestError``.
    """
    roots = _identities(forbidden)
    try:
        out_fd = _open_out_dir(out_dir, roots)
    except OSError as error:
        raise ManifestError("cannot write the results directory") from error
    try:
        try:
            name, run_fd = _new_run_dir(out_fd)
        except OSError as error:
            raise ManifestError("cannot write the results directory") from error
        created: list[str] = []
        try:
            for file in sorted(files, key=lambda name: name == REPORT):  # the report last
                _write_file(run_fd, REPORT_TEMP if file == REPORT else file, files[file], created)
            _refuse_if_contained(run_fd, roots)
            if REPORT in files:
                _publish_report(run_fd, created)
        except BaseException as error:
            _discard(out_fd, name, run_fd, created)
            if isinstance(error, (OSError, ValueError)) and not isinstance(error, ManifestError):
                raise ManifestError("cannot write the results directory") from error
            raise
        finally:
            os.close(run_fd)
        return name
    finally:
        os.close(out_fd)
