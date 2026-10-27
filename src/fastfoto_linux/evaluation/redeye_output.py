"""Where results go: outside the repo, atomically, with private permissions."""

import contextlib
import os
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path

from fastfoto_linux.evaluation.redeye_images import ImageError, read_regular_fd
from fastfoto_linux.evaluation.redeye_manifest import Manifest, ManifestError

PROJECT_NAME = "fastfoto-linux"
MAX_PYPROJECT_BYTES = 1_000_000
DIR_MODE = 0o700
FILE_MODE = 0o600


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


def _write_atomic(dir_fd: int, name: str, text: str) -> None:
    temporary = f".{name}.{os.getpid()}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(temporary, flags, FILE_MODE, dir_fd=dir_fd)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(temporary, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary, dir_fd=dir_fd)
        raise


def _open_out_dir(out_dir: Path, forbidden: Sequence[Path]) -> int:
    """An fd on the output directory, re-validated now: not a symlink, not a forbidden root, not
    inside one, whatever happened to the path since it was first checked."""
    missing = [d for d in (out_dir, *out_dir.parents) if not d.exists()]
    for directory in reversed(missing):  # parents we create are private too
        directory.mkdir(mode=DIR_MODE, exist_ok=True)
    try:
        fd = os.open(
            out_dir, os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0)
        )
    except OSError as error:
        raise ManifestError("the output directory is not a plain directory") from error
    try:
        real = Path(os.readlink(f"/proc/self/fd/{fd}"))
        identity = os.fstat(fd)
        for root in forbidden:
            info = os.stat(root)
            if (info.st_dev, info.st_ino) == (identity.st_dev, identity.st_ino):
                raise ManifestError("the output directory must be outside the manifest directory")
        check_out_allowed(real, [r.resolve() for r in forbidden])
    except BaseException:
        os.close(fd)
        raise
    return fd


def write_outputs(
    out_dir: Path,
    files: Mapping[str, str],
    forbidden: Sequence[Path] = (),
    stale: Sequence[str] = (),
) -> None:
    """Write each file atomically (tmp + replace, relative to an fd on the directory) with mode
    0o600 into a 0o700 directory, after re-checking the directory against ``forbidden``; remove
    the ``stale`` names (outputs of an earlier run that this run does not produce)."""
    fd = _open_out_dir(out_dir, forbidden)
    try:
        for name, text in files.items():
            _write_atomic(fd, name, text)
        for name in stale:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(name, dir_fd=fd)
    finally:
        os.close(fd)
