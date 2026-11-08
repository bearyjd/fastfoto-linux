"""A ``tmp_path`` whose parent folders the OCR model cache will trust, on any dev machine.

The model cache refuses a data folder below a writable folder owned by someone other than
root or you (``ocr_languages._trusted_base``). Rootless containers (toolbox, distrobox,
podman) show the host's root-owned ``/tmp`` as owned by the overflow uid 65534 ("nobody"),
so the cache tests, which put ``XDG_DATA_HOME`` in ``tmp_path``, failed only there.

When that happens the tests move to a private folder in ``$XDG_RUNTIME_DIR``. The check here
is written independently of the production guard: if that guard broke and refused everything,
the tests would still fail rather than be skipped. With nowhere trusted to go, the tests are
skipped on a dev machine and fail under ``CI``, where ``/tmp`` is root-owned.
"""

import os
import shutil
import stat
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

TRUSTED_UIDS = frozenset({0, os.getuid()})
SHARED_WRITE = stat.S_IWGRP | stat.S_IWOTH


def untrusted_ancestor(path: Path) -> str | None:
    """Describe the first folder above (or at) ``path`` the model cache would refuse."""
    resolved = path.resolve()
    for folder in (*reversed(resolved.parents), resolved):
        if os.statvfs(folder).f_flag & os.ST_RDONLY:
            continue
        info = folder.stat()
        if info.st_uid not in TRUSTED_UIDS:
            return f"{folder} is owned by uid {info.st_uid}, neither root nor you"
        if info.st_mode & SHARED_WRITE and not info.st_mode & stat.S_ISVTX:
            return f"{folder} is writable by others and has no sticky bit"
    return None


def _runtime_dir() -> Path | None:
    configured = Path(os.environ.get("XDG_RUNTIME_DIR", ""))
    if not configured.is_absolute() or not configured.is_dir():
        return None
    resolved = configured.resolve()  # the cache compares resolved paths, so the tests must too
    return resolved if untrusted_ancestor(resolved) is None else None


def _remove(folder: Path) -> None:
    """Delete ``folder`` even if a test left folders inside it that you cannot read or write.

    Only real folders inside ``folder`` are unlocked (never a symlink's target, never the
    runtime dir itself); anything still in the way afterwards raises.
    """
    folder.chmod(stat.S_IRWXU)
    for parent, children, _files in os.walk(folder):
        for child in children:  # unlocked before os.walk descends into it
            path = Path(parent, child)
            if stat.S_ISDIR(path.lstat().st_mode):
                path.chmod(stat.S_IRWXU)
    shutil.rmtree(folder)


def trusted_tmp_path(tmp_path: Path) -> Iterator[Path]:
    """Yield ``tmp_path``, or a trusted private stand-in that is removed afterwards."""
    problem = untrusted_ancestor(tmp_path)
    if problem is None:
        yield tmp_path
        return
    runtime = _runtime_dir()
    if runtime is None:
        message = (
            f"the OCR model cache refuses pytest's temp folder ({problem}) and "
            "$XDG_RUNTIME_DIR is not a trusted alternative; rerun with "
            "--basetemp=<a folder whose parents belong to root or you>"
        )
        if os.environ.get("CI"):
            pytest.fail(message)
        pytest.skip(message)
    folder = Path(tempfile.mkdtemp(prefix="fastfoto-ocr-test-", dir=runtime))
    try:
        yield folder
    finally:
        _remove(folder)
