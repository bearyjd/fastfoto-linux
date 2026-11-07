"""A metrics-only corpus report: numbers and tokens, never pixels, text, paths or rights text."""

import json
import math
import re
from collections.abc import Mapping

from fastfoto_linux.evaluation.corpus_manifest import SPLITS, CorpusError, CorpusManifest

REPORT_FORMAT = "fastfoto-corpus-report"
REPORT_VERSION = 1
MAX_LIST_ITEMS = 32
MAX_DEPTH = 8
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
_TOKEN = re.compile(r"[A-Za-z0-9._:+-]{1,64}")  # no whitespace: no sentences, no paths


def _check_key(key: object) -> None:
    if type(key) is not str or not _TOKEN.fullmatch(key):
        raise CorpusError("a report key must be a short token")
    if key.lower() in FORBIDDEN_KEYS:
        raise CorpusError("a report key names data that never belongs in a report")


def _check_leaf(value: object) -> None:
    if value is None or type(value) in (bool, int):
        return
    if type(value) is float and math.isfinite(value):
        return
    if type(value) is str and _TOKEN.fullmatch(value):
        return
    raise CorpusError("a report value must be a number, a boolean, null or a short token")


def _check(value: object, depth: int) -> None:
    if not isinstance(value, (dict, list, tuple)):
        _check_leaf(value)
        return
    if depth > MAX_DEPTH:
        raise CorpusError(f"report values are nested deeper than {MAX_DEPTH} levels")
    if isinstance(value, dict):
        for key, inner in value.items():
            _check_key(key)
            _check(inner, depth + 1)
        return
    if len(value) > MAX_LIST_ITEMS:
        raise CorpusError(f"a report list has more than {MAX_LIST_ITEMS} items")
    for inner in value:
        _check(inner, depth + 1)


def check_metrics_only(obj: object) -> None:
    """Refuse (``CorpusError``) anything but nested numbers, booleans, null and token strings."""
    _check(obj, 1)


def _counts(values: list[str], options: tuple[str, ...]) -> dict[str, int]:
    return {option: values.count(option) for option in options if option in values}


def build_report(manifest: CorpusManifest, metrics: Mapping[str, object]) -> dict:
    """Counts by split and kind, the manifest's hash and the caller's metrics: no item data."""
    items = manifest.items
    return {
        "format": REPORT_FORMAT,
        "version": REPORT_VERSION,
        "manifest_sha256": manifest.sha256,
        "items": {
            "total": len(items),
            "by_split": _counts([i.split for i in items], SPLITS),
            "by_kind": _counts([i.kind for i in items], ("document", "photo")),
        },
        "metrics": dict(metrics),
    }


def serialise_report(report: Mapping[str, object]) -> bytes:
    """Deterministic JSON bytes; the shape check runs first, so nothing unsafe is serialised."""
    check_metrics_only(report)
    text = json.dumps(report, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False)
    return (text + "\n").encode("ascii")
