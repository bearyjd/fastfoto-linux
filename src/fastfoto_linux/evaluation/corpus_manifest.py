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
import unicodedata
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType

from fastfoto_linux.evaluation.corpus_types import CorpusError, CorpusItem, CorpusManifest
from fastfoto_linux.evaluation.corpus_verify import read_verified, verify_hashes
from fastfoto_linux.evaluation.redeye_images import open_resolved_dir, read_up_to
from fastfoto_linux.evaluation.redeye_manifest import ManifestError
from fastfoto_linux.evaluation.redeye_output import check_out_allowed
from fastfoto_linux.evaluation.redeye_split import derived_split

__all__ = [
    "CorpusError",
    "CorpusItem",
    "CorpusManifest",
    "assign_splits",
    "check_outside_checkout",
    "check_relpath",
    "load_corpus_manifest",
    "parse_corpus_manifest",
    "read_verified",
    "verify_hashes",
]
FORMAT = "fastfoto-corpus"
VERSION = 1
MAX_MANIFEST_BYTES = 8_000_000
MAX_ITEMS = 10_000
MAX_TEXT = 512
MAX_ANNOTATION_DEPTH = 8
MAX_ANNOTATION_NODES = 10_000
MAX_TOTAL_ANNOTATION_NODES = 200_000
MAX_PATH = 1024
KINDS = ("photo", "document")
SPLITS = ("tuning", "heldout")
CONSENT_SCOPES = ("private-eval", "redistributable")
ID_PATTERN = r"(?!\.{1,2}$)[A-Za-z0-9._-]{1,128}"
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


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        raise CorpusError("duplicate JSON key in manifest")
    return dict(pairs)


def _invalid_constant(name: str) -> object:
    raise CorpusError(f"{name} is not allowed in the manifest")


def _no_control(value: str, what: str) -> None:
    if any(unicodedata.category(char) == "Cc" for char in value):
        raise CorpusError(f"{what} has a control character")


def check_relpath(rel: str) -> None:
    """Refuse an unsafe item path (absolute, backslash, NUL, control character, too long, empty
    or ``.``/``..`` segment)."""
    if not rel or "\0" in rel or "\\" in rel or rel.startswith("/"):
        raise CorpusError("item path must be a relative POSIX path")
    if len(rel) > MAX_PATH:
        raise CorpusError(f"item path is longer than {MAX_PATH} characters")
    if any(part in ("", ".", "..") for part in rel.split("/")):
        raise CorpusError("item path has an empty, '.' or '..' segment")
    _no_control(rel, "item path")


def _dict(value: object, keys: frozenset[str], required: frozenset[str], what: str) -> dict:
    if type(value) is not dict:
        raise CorpusError(f"{what} must be an object")
    missing = sorted(required - value.keys())
    if missing:
        raise CorpusError(f"{what} is missing required field {missing[0]!r}")
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
    _no_control(value, what)
    return value


def _limited_text(value: object, what: str) -> str:
    if type(value) is str and len(value) > MAX_TEXT:
        raise CorpusError(f"{what} is longer than {MAX_TEXT} characters")
    return _text(value, what)


def _choice(value: object, options: Sequence[str], what: str) -> str:
    if type(value) is not str or value not in options:
        raise CorpusError(f"{what} must be one of: {', '.join(options)}")
    return value


def _count_nodes(value: object, limit: int) -> int:
    """JSON values in ``value`` (itself included), counted iteratively; stops past ``limit``."""
    count, stack = 0, [value]
    while stack:
        node = stack.pop()
        count += 1
        if count > limit:
            break
        if type(node) is dict:
            stack.extend(node.values())
        elif type(node) is list:
            stack.extend(node)
    return count


def _freeze(value: object, depth: int) -> object:
    """A deeply immutable copy of a JSON value (the node count is already bounded)."""
    if isinstance(value, (dict, list)) and depth > MAX_ANNOTATION_DEPTH:
        raise CorpusError(f"annotations are nested deeper than {MAX_ANNOTATION_DEPTH} levels")
    if type(value) is dict:
        return MappingProxyType(
            {_encodable(k, "annotation key"): _freeze(v, depth + 1) for k, v in value.items()}
        )
    if type(value) is list:
        return tuple(_freeze(v, depth + 1) for v in value)
    if type(value) is str:
        return _encodable(value, "annotation text")
    if (
        value is None
        or type(value) in (bool, int)
        or (type(value) is float and math.isfinite(value))
    ):
        return value
    raise CorpusError("annotations hold a value that is not finite JSON")


def _annotations(value: object, budget: int) -> tuple[Mapping[str, object], int]:
    """The frozen annotations and their node count; ``budget`` is what the manifest has left."""
    if type(value) is not dict:
        raise CorpusError("annotations must be an object")
    for key, inner in value.items():
        if not _ANNOTATION_KEY.fullmatch(key) or type(inner) is not dict:
            raise CorpusError("annotations must map lowercase names to objects")
    nodes = _count_nodes(value, min(MAX_ANNOTATION_NODES, budget))
    if nodes > MAX_ANNOTATION_NODES:
        raise CorpusError(f"annotations are too large (over {MAX_ANNOTATION_NODES} values)")
    if nodes > budget:
        raise CorpusError("the annotations of the whole manifest are too large")
    return _freeze(value, 1), nodes  # type: ignore[return-value]  # a dict is frozen to a mapping


def _item(value: object, budget: int) -> tuple[CorpusItem, int]:
    raw = _dict(value, _ITEM_KEYS, ITEM_REQUIRED, "item")
    path = _text(raw["path"], "path")
    check_relpath(path)
    group = raw.get("group")
    notes, nodes = _annotations(raw["annotations"], budget)
    item = CorpusItem(
        id=_text(raw["id"], "id", _ID),
        path=path,
        sha256=_text(raw["sha256"], "sha256", _SHA),
        kind=_choice(raw["kind"], KINDS, "kind"),
        split=_choice(raw["split"], SPLITS, "split"),
        source=_limited_text(raw["source"], "source"),
        licence=_limited_text(raw["licence"], "licence"),
        consent_scope=_choice(raw["consent_scope"], CONSENT_SCOPES, "consent_scope"),
        annotations=notes,
        group=None if group is None else _text(group, "group", _ID),
    )
    return item, nodes


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
    """Validate manifest bytes; every problem is a ``CorpusError``.

    On success the returned manifest takes ownership of ``root_fd`` (``close()`` closes it); on
    an error the caller still owns it.
    """
    if len(data) > MAX_MANIFEST_BYTES:
        raise CorpusError("manifest is too large")
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
    items, budget = [], MAX_TOTAL_ANNOTATION_NODES
    for entry in top["items"]:
        item, nodes = _item(entry, budget)
        items.append(item)
        budget -= nodes
    parsed = tuple(items)
    _unique([i.id for i in parsed], "id")
    _unique([i.sha256 for i in parsed], "sha256")
    _unique([i.path for i in parsed], "path")
    _check_splits(seed, parsed)
    return CorpusManifest(seed, parsed, hashlib.sha256(data).hexdigest(), root, root_fd)


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


def check_outside_checkout(path: Path) -> None:
    """Refuse (``CorpusError``) a ``path`` that is, or is inside, a fastfoto-linux checkout."""
    try:
        check_out_allowed(path, [])
    except ManifestError as error:
        if "cannot verify" in str(error):  # fail closed, but say it could not be told
            raise CorpusError(
                "cannot verify whether the corpus is inside the fastfoto-linux checkout"
            ) from None
        raise CorpusError("the corpus must be outside the fastfoto-linux checkout") from None


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


def _manifest_location(path: Path) -> Path:
    raw = os.fspath(path)
    if "\0" in raw or not raw.startswith("/") or any(p in (".", "..") for p in raw.split("/")):
        raise CorpusError("the manifest path must be absolute, without '.', '..' or NUL")
    location = Path(raw)
    if not location.name:
        raise CorpusError("the manifest path must name a file")
    return location


def load_corpus_manifest(path: Path, verify: bool = True) -> CorpusManifest:
    """Read (at most ``MAX_MANIFEST_BYTES``) and validate the manifest at ``path``.

    ``path`` must be absolute with no ``.``/``..``. Its directory is walked from ``/`` without
    following a symlink and the file is opened ``O_NOFOLLOW`` (a symlinked manifest is refused);
    the directory is refused inside a fastfoto-linux checkout. The directory stays open
    (``CorpusManifest.root_fd``) and, with ``verify``, every item is re-hashed through it, so no
    path is resolved twice. The caller closes the manifest.
    """
    location = _manifest_location(path)
    try:
        dir_fd = open_resolved_dir(location.parent)
    except OSError:
        raise CorpusError("cannot read the manifest file") from None
    try:
        check_outside_checkout(location.parent)
        manifest = parse_corpus_manifest(
            _read_manifest_file(dir_fd, location.name), location.parent, dir_fd
        )
        if verify:
            verify_hashes(manifest)
        return manifest
    except OSError:
        os.close(dir_fd)
        raise CorpusError("cannot read the manifest file") from None
    except BaseException:
        os.close(dir_fd)
        raise
