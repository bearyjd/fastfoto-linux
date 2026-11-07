"""The corpus manifest: a rights-aware, versioned JSON file, validated strictly.

Library only. It ships no data; ``load_corpus_manifest`` reads a manifest the user points at
and (by default) re-hashes every file it names through a pinned directory descriptor.
"""

import contextlib
import hashlib
import json
import math
import os
import re
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

from fastfoto_linux.evaluation.redeye_images import (
    ImageError,
    PinnedRoot,
    open_resolved_dir,
    read_up_to,
)
from fastfoto_linux.evaluation.redeye_split import derived_split

FORMAT = "fastfoto-corpus"
VERSION = 1
MAX_MANIFEST_BYTES = 8_000_000
MAX_ITEMS = 10_000
MAX_FILE_BYTES = 4 * 1024**3
HASH_CHUNK = 1 << 20
MAX_TEXT = 512
MAX_ANNOTATION_DEPTH = 8
MAX_ANNOTATION_NODES = 10_000
KINDS = ("photo", "document")
SPLITS = ("tuning", "heldout")
CONSENT_SCOPES = ("private-eval", "redistributable")
ID_PATTERN = "[A-Za-z0-9._-]{1,128}"
SHA_PATTERN = "[0-9a-f]{64}"
SEED_PATTERN = "[0-9a-f]{16,64}"
ANNOTATION_KEY_PATTERN = "[a-z][a-z0-9_]{0,31}"
TOP_KEYS = frozenset({"format", "version", "split_seed", "items"})
ITEM_REQUIRED = frozenset(
    {
        "id",
        "path",
        "sha256",
        "kind",
        "split",
        "source",
        "licence",
        "consent_scope",
        "annotations",
    }
)
_ITEM_KEYS = ITEM_REQUIRED | {"group"}
_ID = re.compile(ID_PATTERN)
_SHA = re.compile(SHA_PATTERN)
_SEED = re.compile(SEED_PATTERN)
_ANNOTATION_KEY = re.compile(ANNOTATION_KEY_PATTERN)


class CorpusError(ValueError):
    """The corpus manifest, its location or one of its files is not acceptable."""


@dataclass(frozen=True)
class CorpusItem:
    id: str
    path: str
    sha256: str
    kind: str
    split: str
    source: str
    licence: str
    consent_scope: str
    annotations: Mapping[str, object]
    group: str | None = None


@dataclass(frozen=True)
class CorpusManifest:
    """A validated manifest. ``root_fd`` pins the manifest's directory; the caller closes it."""

    split_seed: str
    items: tuple[CorpusItem, ...]
    sha256: str
    root: Path | None = None
    root_fd: int | None = field(default=None, repr=False)

    def close(self) -> None:
        if self.root_fd is not None:
            fd = self.root_fd
            object.__setattr__(self, "root_fd", None)  # frozen: only close() lets go of the fd
            os.close(fd)

    def __enter__(self) -> "CorpusManifest":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        raise CorpusError("duplicate JSON key in manifest")
    return dict(pairs)


def _invalid_constant(name: str) -> object:
    raise CorpusError(f"{name} is not allowed in the manifest")


def check_relpath(rel: str) -> None:
    """Refuse an unsafe item path (absolute, backslash, NUL, empty or ``.``/``..`` segment)."""
    if not rel or "\0" in rel or "\\" in rel or rel.startswith("/"):
        raise CorpusError("item path must be a relative POSIX path")
    if any(part in ("", ".", "..") for part in rel.split("/")):
        raise CorpusError("item path has an empty, '.' or '..' segment")


def _dict(value: object, keys: frozenset[str], required: frozenset[str], what: str) -> dict:
    if type(value) is not dict:
        raise CorpusError(f"{what} must be an object")
    for name in sorted(required - value.keys()):
        raise CorpusError(f"{what} is missing required field {name!r}")
    if value.keys() - keys:
        raise CorpusError(f"{what} has an unknown field")
    return value


def _text(value: object, what: str, pattern: re.Pattern[str] | None = None) -> str:
    if type(value) is not str or not value.strip() or (pattern and not pattern.fullmatch(value)):
        raise CorpusError(f"{what} is not valid")
    return _encodable(value, what)


def _encodable(value: str, what: str) -> str:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:  # a lone surrogate from a \\ud800 escape
        raise CorpusError(f"{what} is not valid text") from error
    return value


def _limited_text(value: object, what: str) -> str:
    if type(value) is str and len(value) > MAX_TEXT:
        raise CorpusError(f"{what} is longer than {MAX_TEXT} characters")
    return _text(value, what)


def _choice(value: object, options: Sequence[str], what: str) -> str:
    if type(value) is not str or value not in options:
        raise CorpusError(f"{what} must be one of: {', '.join(options)}")
    return value


def _freeze(value: object, depth: int) -> tuple[object, int]:
    """A deeply immutable copy of a JSON value and its node count."""
    if isinstance(value, (dict, list)) and depth > MAX_ANNOTATION_DEPTH:
        raise CorpusError(f"annotations are nested deeper than {MAX_ANNOTATION_DEPTH} levels")
    if type(value) is dict:
        pairs = [(_encodable(k, "annotation key"), _freeze(v, depth + 1)) for k, v in value.items()]
        return (
            MappingProxyType({k: frozen for k, (frozen, _) in pairs}),
            1 + sum(n for _, (_, n) in pairs),
        )
    if type(value) is list:
        parts = [_freeze(v, depth + 1) for v in value]
        return tuple(frozen for frozen, _ in parts), 1 + sum(n for _, n in parts)
    if type(value) is str:
        return _encodable(value, "annotation text"), 1
    if value is None or type(value) in (bool, int):
        return value, 1
    if type(value) is float and math.isfinite(value):
        return value, 1
    raise CorpusError("annotations hold a value that is not finite JSON")


def _annotations(value: object) -> Mapping[str, object]:
    if type(value) is not dict:
        raise CorpusError("annotations must be an object")
    for key, inner in value.items():
        if not _ANNOTATION_KEY.fullmatch(key) or type(inner) is not dict:
            raise CorpusError("annotations must map lowercase names to objects")
    frozen, nodes = _freeze(value, 1)
    if nodes > MAX_ANNOTATION_NODES:
        raise CorpusError(f"annotations are too large (over {MAX_ANNOTATION_NODES} values)")
    return frozen  # type: ignore[return-value]  # a dict is frozen to a mapping


def _item(value: object) -> CorpusItem:
    raw = _dict(value, _ITEM_KEYS, ITEM_REQUIRED, "item")
    path = _text(raw["path"], "path")
    check_relpath(path)
    group = raw.get("group")
    return CorpusItem(
        id=_text(raw["id"], "id", _ID),
        path=path,
        sha256=_text(raw["sha256"], "sha256", _SHA),
        kind=_choice(raw["kind"], KINDS, "kind"),
        split=_choice(raw["split"], SPLITS, "split"),
        source=_limited_text(raw["source"], "source"),
        licence=_limited_text(raw["licence"], "licence"),
        consent_scope=_choice(raw["consent_scope"], CONSENT_SCOPES, "consent_scope"),
        annotations=_annotations(raw["annotations"]),
        group=None if group is None else _text(group, "group", _ID),
    )


def _unique(values: list[str], what: str) -> None:
    if len(set(values)) != len(values):
        raise CorpusError(f"duplicate item {what}")


def _check_seed(seed: object) -> str:
    return _text(seed, "split_seed", _SEED)


def _check_splits(seed: str, items: tuple[CorpusItem, ...]) -> None:
    for item in items:
        if item.split != derived_split(seed, item.group, item.sha256):
            raise CorpusError(f"declared split of item {item.id!r} differs from the derived one")


def parse_corpus_manifest(
    data: bytes, root: Path | None = None, root_fd: int | None = None
) -> CorpusManifest:
    """Validate manifest bytes; every problem is a ``CorpusError``."""
    try:
        raw = json.loads(data, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    except (ValueError, RecursionError) as error:
        if isinstance(error, CorpusError):
            raise
        raise CorpusError("manifest is not valid JSON") from error
    top = _dict(raw, TOP_KEYS, TOP_KEYS, "manifest")
    if top["format"] != FORMAT or type(top["version"]) is not int or top["version"] != VERSION:
        raise CorpusError(f"not a version {VERSION} {FORMAT} manifest")
    seed = _check_seed(top["split_seed"])
    if type(top["items"]) is not list or len(top["items"]) > MAX_ITEMS:
        raise CorpusError(f"items must be a list of at most {MAX_ITEMS} items")
    items = tuple(_item(i) for i in top["items"])
    _unique([i.id for i in items], "id")
    _unique([i.sha256 for i in items], "sha256")
    _unique([i.path for i in items], "path")
    _check_splits(seed, items)
    return CorpusManifest(seed, items, hashlib.sha256(data).hexdigest(), root, root_fd)


def assign_splits(items_raw: Sequence[Mapping[str, object]], seed: str) -> list[dict]:
    """New item dicts with ``split`` filled from the seed (for authoring a manifest)."""
    _check_seed(seed)
    out = []
    for raw in items_raw:
        sha = _text(raw.get("sha256"), "sha256", _SHA)
        group = raw.get("group")
        group = None if group is None else _text(group, "group", _ID)
        out.append({**raw, "split": derived_split(seed, group, sha)})
    return out


def _item_error(item: CorpusItem, what: str) -> CorpusError:
    return CorpusError(f"item {item.id!r}: {what}")


def _open_item(pinned: PinnedRoot, item: CorpusItem) -> int:
    try:
        return pinned.open_beneath(item.path)
    except FileNotFoundError:
        raise _item_error(item, "file is missing") from None
    except (OSError, ImageError, ValueError):  # ELOOP (symlink), ENOTDIR, ...
        raise _item_error(item, "unsafe path (a symlink or not openable)") from None


def _digest(fd: int, item: CorpusItem) -> str:
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise _item_error(item, "not a regular file")
        if info.st_size > MAX_FILE_BYTES:
            raise _item_error(item, "file is too large")
        digest, total = hashlib.sha256(), 0
        while chunk := read_up_to(fd, HASH_CHUNK):
            total += len(chunk)
            if total > MAX_FILE_BYTES:
                raise _item_error(item, "file is too large")
            digest.update(chunk)
    except OSError:
        raise _item_error(item, "file is unreadable") from None
    return digest.hexdigest()


def verify_hashes(manifest: CorpusManifest) -> None:
    """Re-hash every file through the manifest's pinned directory; a mismatch names the id only."""
    if manifest.root_fd is None:
        raise CorpusError("the manifest is closed")
    try:
        pinned = PinnedRoot(manifest.root_fd)
    except ImageError:
        raise CorpusError("cannot pin the corpus directory") from None
    with pinned:
        for item in manifest.items:
            fd = _open_item(pinned, item)
            try:
                actual = _digest(fd, item)
            finally:
                with contextlib.suppress(OSError):
                    os.close(fd)
            if actual != item.sha256:
                raise _item_error(item, "content does not match its sha256")


def _read_manifest_file(dir_fd: int, name: str) -> bytes:
    # O_NONBLOCK: opening a FIFO must not wait for a writer.
    flags = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(name, flags, dir_fd=dir_fd)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise CorpusError("the manifest must be a regular file")
        return read_up_to(fd, MAX_MANIFEST_BYTES + 1)
    finally:
        with contextlib.suppress(OSError):
            os.close(fd)


def load_corpus_manifest(path: Path, verify: bool = True) -> CorpusManifest:
    """Read (at most ``MAX_MANIFEST_BYTES``) and validate the manifest at ``path``.

    The directory is walked from ``/`` without following a symlink and kept open
    (``CorpusManifest.root_fd``); the file is read and, with ``verify``, every item re-hashed
    through that descriptor, so no path is resolved twice. The caller closes the manifest.
    """
    try:
        resolved = path.resolve(strict=True)
        dir_fd = open_resolved_dir(resolved.parent)
    except OSError:
        raise CorpusError("cannot read the manifest file") from None
    try:
        data = _read_manifest_file(dir_fd, resolved.name)
        if len(data) > MAX_MANIFEST_BYTES:
            raise CorpusError("manifest is too large")
        manifest = parse_corpus_manifest(data, resolved.parent, dir_fd)
        if verify:
            verify_hashes(manifest)
        return manifest
    except OSError:
        os.close(dir_fd)
        raise CorpusError("cannot read the manifest file") from None
    except BaseException:
        os.close(dir_fd)
        raise
