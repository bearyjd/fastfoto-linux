"""Reading corpus files through the manifest's pinned directory, checked against their sha256."""

import contextlib
import hashlib
import os
import stat
from collections.abc import Callable

from fastfoto_linux.evaluation.corpus_types import CorpusError, CorpusItem, CorpusManifest
from fastfoto_linux.evaluation.redeye_images import ImageError, PinnedRoot, read_up_to

MAX_FILE_BYTES = 4 * 1024**3
MAX_READ_BYTES = 1024**3
MAX_TOTAL_BYTES = 256 * 1024**3
HASH_CHUNK = 1 << 20


def _item_error(item: CorpusItem, what: str) -> CorpusError:
    return CorpusError(f"item {item.id!r}: {what}")


def _pin(manifest: CorpusManifest) -> PinnedRoot:
    if manifest.root_fd is None:
        raise CorpusError("the manifest is closed")
    try:
        return PinnedRoot(manifest.root_fd)
    except ImageError:
        raise CorpusError("cannot pin the corpus directory") from None


def _open_item(pinned: PinnedRoot, item: CorpusItem) -> int:
    try:
        return pinned.open_beneath(item.path)
    except FileNotFoundError:
        raise _item_error(item, "file is missing") from None
    except (OSError, ImageError, ValueError):  # ELOOP (symlink), ENOTDIR, ...
        raise _item_error(item, "unsafe path (a symlink or not openable)") from None


def _stream(fd: int, item: CorpusItem, limit: int, remaining: int, sink: Callable) -> int:
    """Feed the regular file on ``fd`` to ``sink``; ``limit`` per file, ``remaining`` overall.
    The size from fstat is charged before any byte is read. Returns the bytes read."""
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise _item_error(item, "not a regular file")
        if info.st_size > min(limit, remaining):
            raise _item_error(item, "file is too large")
        total = 0
        while chunk := read_up_to(fd, HASH_CHUNK):
            total += len(chunk)
            if total > min(limit, remaining):
                raise _item_error(item, "file is too large")
            sink(chunk)
    except OSError:
        raise _item_error(item, "file is unreadable") from None
    return total


def _read_item(
    pinned: PinnedRoot, item: CorpusItem, limit: int, remaining: int, keep: bool
) -> tuple[int, bytes]:
    digest, chunks = hashlib.sha256(), []

    def sink(chunk: bytes) -> None:
        digest.update(chunk)
        if keep:
            chunks.append(chunk)

    fd = _open_item(pinned, item)
    try:
        total = _stream(fd, item, limit, remaining, sink)
    finally:
        with contextlib.suppress(OSError):
            os.close(fd)
    if digest.hexdigest() != item.sha256:
        raise _item_error(item, "content does not match its sha256")
    return total, b"".join(chunks)


def verify_hashes(manifest: CorpusManifest) -> None:
    """Re-hash every file through the manifest's pinned directory (at most ``MAX_FILE_BYTES``
    each and ``MAX_TOTAL_BYTES`` in all); a failure names the item id only."""
    remaining = MAX_TOTAL_BYTES
    with _pin(manifest) as pinned:
        for item in manifest.items:
            total, _ = _read_item(pinned, item, MAX_FILE_BYTES, remaining, False)
            remaining -= total


def read_verified(manifest: CorpusManifest, item: CorpusItem) -> bytes:
    """The bytes of ``item``, read through the pinned directory and checked against its sha256.

    Consumers must use this (not a path they open themselves) so the bytes they measure are the
    bytes the manifest vouches for. At most ``MAX_READ_BYTES``.
    """
    pinned = _pin(manifest)
    with pinned:
        if item not in manifest.items:
            raise CorpusError("the item is not in this manifest")
        return _read_item(pinned, item, MAX_READ_BYTES, MAX_READ_BYTES, True)[1]
