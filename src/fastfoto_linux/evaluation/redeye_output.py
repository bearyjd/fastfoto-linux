"""Where results go: outside the repo, atomically, with private permissions."""

import os
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path

from fastfoto_linux.evaluation.redeye_manifest import Manifest, ManifestError

PROJECT_NAME = "fastfoto-linux"
MAX_PYPROJECT_BYTES = 1_000_000
DIR_MODE = 0o700
FILE_MODE = 0o600


def _is_project_checkout(directory: Path) -> bool:
    if not (directory / ".git").exists():
        return False
    try:
        with (directory / "pyproject.toml").open("rb") as handle:
            data = handle.read(MAX_PYPROJECT_BYTES)
        return tomllib.loads(data.decode()).get("project", {}).get("name") == PROJECT_NAME
    except (OSError, ValueError):
        return False


def _default_out(manifest: Manifest, env: Mapping[str, str]) -> Path:
    cache = env.get("XDG_CACHE_HOME")
    if cache and not Path(cache).is_absolute():
        raise ManifestError("XDG_CACHE_HOME must be an absolute path")
    base = Path(cache) if cache else Path(env.get("HOME") or Path.home()) / ".cache"
    return base / "fastfoto-linux" / "redeye-eval" / manifest.sha256[:12]


def resolve_out_dir(manifest: Manifest, out: Path | None, env: Mapping[str, str]) -> Path:
    """``out`` (or the cache default), refused inside the manifest root or the project checkout."""
    resolved = (out if out is not None else _default_out(manifest, env)).expanduser().resolve()
    if manifest.root == resolved or manifest.root in resolved.parents:
        raise ManifestError("the output directory must be outside the manifest directory")
    if any(_is_project_checkout(d) for d in (resolved, *resolved.parents)):
        raise ManifestError("the output directory must be outside the fastfoto-linux checkout")
    return resolved


def _write_atomic(path: Path, text: str) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, FILE_MODE)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def write_outputs(
    out_dir: Path,
    files: Mapping[str, str],
    forbidden: Sequence[Path] = (),
    stale: Sequence[str] = (),
) -> None:
    """Write each file atomically (tmp + replace) with mode 0o600 into a 0o700 directory."""
    missing = [d for d in (out_dir, *out_dir.parents) if not d.exists()]
    for directory in reversed(missing):  # parents we create are private too
        directory.mkdir(mode=DIR_MODE, exist_ok=True)
    for name, text in files.items():
        _write_atomic(out_dir / name, text)
