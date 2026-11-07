"""A metrics-only corpus report: numbers and tokens, never pixels, text, paths or rights text."""

import json
import math
import re
from collections.abc import Iterator, Mapping
from pathlib import PurePosixPath

from fastfoto_linux.evaluation.corpus_manifest import (
    KINDS,
    SHA_PATTERN,
    SPLITS,
    CorpusError,
    CorpusManifest,
)

REPORT_FORMAT = "fastfoto-corpus-report"
REPORT_VERSION = 1
MAX_LIST_ITEMS = 32
MAX_DEPTH = 8
MAX_DICT_KEYS = 64
MAX_INT = 2**53
KEY_PATTERN = "[a-z][a-z0-9_]{0,47}"
REPORT_STRINGS = frozenset(
    (*SPLITS, *KINDS, "pass", "fail", "abstain", "insufficient_data", "not_applicable")
)
FORBIDDEN_KEYS = frozenset(
    {
        "pixels",
        "pixel",
        "image",
        "images",
        "crop",
        "crops",
        "thumbnail",
        "thumbnails",
        "text",
        "ocr_text",
        "path",
        "paths",
        "source",
        "licence",
        "filename",
        "name",
        "id",
        "ids",
        "bytes",
        "data",
        "ground_truth",
        "annotations",
    }
)
_KEY = re.compile(KEY_PATTERN)
_SHA = re.compile(SHA_PATTERN)
_FORBIDDEN = frozenset(key.replace("_", "") for key in FORBIDDEN_KEYS)
_ENVELOPE = ("format", "version", "manifest_sha256", "items", "metrics")


def _check_key(key: object) -> None:
    if type(key) is not str or not _KEY.fullmatch(key):
        raise CorpusError("a report key must be a short lowercase name")
    if key.replace("_", "") in _FORBIDDEN:
        raise CorpusError("a report key names data that never belongs in a report")


def _check_leaf(value: object) -> None:
    if value is None or type(value) is bool:
        return
    if type(value) is int and abs(value) < MAX_INT:
        return
    if type(value) is float and math.isfinite(value):
        return
    if type(value) is str and value in REPORT_STRINGS:
        return
    raise CorpusError("a report value must be a number, a boolean, null or a fixed status word")


def _check(value: object, depth: int) -> None:
    if not isinstance(value, (dict, list, tuple)):
        _check_leaf(value)
        return
    if depth > MAX_DEPTH:
        raise CorpusError(f"report values are nested deeper than {MAX_DEPTH} levels")
    if isinstance(value, dict):
        if len(value) > MAX_DICT_KEYS:
            raise CorpusError(f"a report object has more than {MAX_DICT_KEYS} keys")
        for key, inner in value.items():
            _check_key(key)
            _check(inner, depth + 1)
        return
    if len(value) > MAX_LIST_ITEMS:
        raise CorpusError(f"a report list has more than {MAX_LIST_ITEMS} items")
    for inner in value:
        _check(inner, depth + 1)


def check_metrics_only(obj: object) -> None:
    """Refuse (``CorpusError``) anything but nested numbers, booleans, null, fixed status words
    (``REPORT_STRINGS``) and short lowercase keys outside ``FORBIDDEN_KEYS``.

    A shape check, not a privacy proof: it cannot tell a harmless number from a leaked one.
    """
    _check(obj, 1)


def _strings(value: object, keys: bool = True) -> Iterator[str]:
    """Every string in a nested value, iteratively (and its dict keys when ``keys``)."""
    stack = [value]
    while stack:
        node = stack.pop()
        if isinstance(node, str):
            yield node
        elif isinstance(node, Mapping):
            if keys:
                stack.extend(node.keys())
            stack.extend(node.values())
        elif isinstance(node, (list, tuple)):
            stack.extend(node)


def _private_strings(manifest: CorpusManifest) -> frozenset[str]:
    """Lowercased ids, groups, path parts (with and without suffix) and free text of the items."""
    found: set[str] = set()
    for item in manifest.items:
        found.update((item.id, item.group or "", item.source, item.licence))
        for part in item.path.split("/"):
            found.update((part, PurePosixPath(part).stem, part.split(".")[0]))
        for inner in item.annotations.values():  # the top-level names are schema words
            found.update(_strings(inner))
    return frozenset(text.lower() for text in found if text)


def _refuse_echoes(manifest: CorpusManifest, metrics: Mapping[str, object]) -> None:
    private = _private_strings(manifest)
    if any(text.lower() in private for text in _strings(metrics)):
        raise CorpusError("the metrics repeat a string taken from the manifest")


def _counts(values: list[str], options: tuple[str, ...]) -> dict[str, int]:
    return {option: values.count(option) for option in options}


def build_report(manifest: CorpusManifest, metrics: Mapping[str, object]) -> dict:
    """Counts by split and kind, the manifest's hash and the caller's metrics: no item data.

    Metrics whose keys or strings equal (ignoring case) an id, group, path part, source,
    licence or annotation text of the manifest are refused.
    """
    _refuse_echoes(manifest, metrics)
    items = manifest.items
    return {
        "format": REPORT_FORMAT,
        "version": REPORT_VERSION,
        "manifest_sha256": manifest.sha256,
        "items": {
            "total": len(items),
            "by_split": _counts([i.split for i in items], SPLITS),
            "by_kind": _counts([i.kind for i in items], KINDS),
        },
        "metrics": dict(metrics),
    }


def _check_envelope(report: Mapping[str, object]) -> None:
    sha = report.get("manifest_sha256")
    if tuple(sorted(report)) != tuple(sorted(_ENVELOPE)) or report["format"] != REPORT_FORMAT:
        raise CorpusError("the report does not have the expected fields")
    if report["version"] != REPORT_VERSION or type(sha) is not str or not _SHA.fullmatch(sha):
        raise CorpusError("the report header is not valid")
    check_metrics_only({"items": report["items"], "metrics": report["metrics"]})


def serialise_report(report: Mapping[str, object]) -> bytes:
    """Deterministic JSON bytes; the shape check runs first, so nothing unsafe is serialised."""
    _check_envelope(report)
    text = json.dumps(report, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False)
    return (text + "\n").encode("ascii")
