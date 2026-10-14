"""Write new files without ever overwriting, all-or-nothing."""

import errno
import logging
import os
import secrets
from collections.abc import Iterable, Sequence
from pathlib import Path

from fastfoto_linux.output.errors import OutputCollisionError

logger = logging.getLogger(__name__)

TEMP_SUFFIX = ".tmp"
TEMP_TOKEN_BYTES = 4
# link() errors that mean "this filesystem has no hard links" (FAT/exFAT, some network mounts).
_NO_HARD_LINKS = frozenset({errno.EPERM, errno.ENOTSUP, errno.ENOSYS})


def write_new_files(items: Sequence[tuple[Path, bytes]]) -> None:
    """Write every ``(path, data)`` pair as a new file, or none of them.

    Each file is staged under a temporary name in its own folder, then published without
    replacing anything: an existing file raises OutputCollisionError. If any file fails, the
    files this call already published and every temporary file are removed again.
    """
    staged: list[tuple[Path, Path]] = []
    published: list[Path] = []
    try:
        for target, data in items:
            staged.append((_write_temp(target, data), target))
        for temp, target in staged:
            _publish(temp, target, published)
    except BaseException:
        _discard([*published, *(temp for temp, _ in staged)])
        raise


def _write_temp(target: Path, data: bytes) -> Path:
    token = secrets.token_hex(TEMP_TOKEN_BYTES)
    temp = target.with_name(f".{target.name}.{token}{TEMP_SUFFIX}")
    try:
        with temp.open("xb") as handle:
            handle.write(data)
    except BaseException:
        _discard([temp])
        raise
    return temp


def _publish(temp: Path, target: Path, published: list[Path]) -> None:
    try:
        os.link(temp, target)
    except FileExistsError as exc:
        raise _collision(target) from exc
    except OSError as exc:
        if exc.errno not in _NO_HARD_LINKS:
            raise
        _reserve_then_replace(temp, target, published)
        return
    published.append(target)
    temp.unlink()


def _reserve_then_replace(temp: Path, target: Path, published: list[Path]) -> None:
    """Fallback for filesystems without hard links: claim the name exclusively, then swap."""
    try:
        target.open("xb").close()
    except FileExistsError as exc:
        raise _collision(target) from exc
    published.append(target)
    os.replace(temp, target)


def _collision(target: Path) -> OutputCollisionError:
    return OutputCollisionError(f"{target} already exists; refusing to overwrite it")


def _discard(paths: Iterable[Path]) -> None:
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("could not remove %s while cleaning up", path, exc_info=True)
