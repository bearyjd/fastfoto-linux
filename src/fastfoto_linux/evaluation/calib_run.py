"""Run one calibration feature over a corpus manifest: guards, measurement, report, gate.

The contract (red-eye's, on the corpus manifest): a ``--split heldout`` run needs the manifest's
sha256 pinned and refuses on any leak between the splits; a pin that does not match is refused
for either split; the report holds metrics only and is byte-identical on a rerun; the gate fails
on any failed or insufficient criterion and on any errored item. Every refusal is a
``CorpusError`` (or ``ManifestError`` for the output location) that names item ids only.
"""

import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from fastfoto_linux.evaluation import calib_colour, calib_deskew, calib_detail, calib_wb
from fastfoto_linux.evaluation.calib_annotations import PARSERS
from fastfoto_linux.evaluation.calib_metrics import rounded
from fastfoto_linux.evaluation.calib_thresholds import FAIL, INSUFFICIENT, NOT_APPLICABLE, judge
from fastfoto_linux.evaluation.corpus_manifest import SHA_PATTERN, SPLITS, read_verified
from fastfoto_linux.evaluation.corpus_report import build_report, serialise_report
from fastfoto_linux.evaluation.corpus_types import CorpusError, CorpusItem, CorpusManifest
from fastfoto_linux.evaluation.redeye_manifest import ManifestError
from fastfoto_linux.evaluation.redeye_output import check_out_allowed, write_outputs
from fastfoto_linux.evaluation.redeye_split import Fingerprint, count_leaks

FEATURES = {
    "deskew": calib_deskew,
    "autocolour": calib_colour,
    "wb": calib_wb,
    "detail": calib_detail,
}
REPORT = "report.json"
_SHA = re.compile(SHA_PATTERN)
_GATE_FAILING = (FAIL, INSUFFICIENT)

Selected = list[tuple[CorpusItem, object]]


@dataclass(frozen=True)
class CalibResult:
    report: bytes
    errored: int
    failures: tuple[str, ...]  # why the gate would fail (criterion keys and a fixed phrase)
    pending: tuple[str, ...] = ()  # criteria no command judges (a human does)


def check_request(split: str, expect_sha256: str | None, gate: bool) -> None:
    """The usage rules, before anything is read: a held-out run (and so a gate) needs the pin."""
    if split not in SPLITS:
        raise CorpusError("--split must be tuning or heldout")
    if expect_sha256 is not None and not _SHA.fullmatch(expect_sha256):
        raise CorpusError("--expect-manifest-sha256 must be 64 lowercase hexadecimal digits")
    if split == "heldout" and expect_sha256 is None:
        raise CorpusError("--split heldout needs --expect-manifest-sha256 (freeze the set first)")
    if gate and split != "heldout":
        raise CorpusError("--gate needs --split heldout and --expect-manifest-sha256")


def check_pin(manifest: CorpusManifest, expect_sha256: str | None) -> None:
    if expect_sha256 is not None and expect_sha256 != manifest.sha256:
        raise CorpusError("the manifest does not match --expect-manifest-sha256")


def _select(manifest: CorpusManifest, feature: str, split: str) -> tuple[Selected, int]:
    """The annotated items of the feature's kind in ``split`` with their parsed annotations, and
    how many items of that kind and split lack the annotation (skipped, only counted)."""
    selected: Selected = []
    skipped = 0
    for item in manifest.items:
        if item.kind != FEATURES[feature].KIND or item.split != split:
            continue
        if feature not in item.annotations:
            skipped += 1
            continue
        try:
            selected.append((item, PARSERS[feature](item.annotations[feature])))
        except CorpusError as error:
            raise CorpusError(f"item {item.id!r}: {error}") from None
    return selected, skipped


def _fingerprints(manifest: CorpusManifest, feature: str, split: str) -> list[Fingerprint]:
    """Every item of the feature's kind in ``split``, annotated or not. An item that cannot be
    fingerprinted refuses the run: leakage could not be ruled out."""
    prints = []
    for item in manifest.items:
        if item.kind != FEATURES[feature].KIND or item.split != split:
            continue
        try:
            pixels = FEATURES[feature].digest(read_verified(manifest, item))
        except Exception:
            raise CorpusError(
                f"{split} item {item.id!r} cannot be read, so held-out leakage cannot be ruled out"
            ) from None
        prints.append(Fingerprint(item.id, item.sha256, pixels, item.group))
    return prints


def check_leaks(manifest: CorpusManifest, feature: str) -> None:
    """Refuse a held-out run when a held-out item shares its pixels (or file, id, group) with a
    tuning item of the same kind, annotated or not."""
    total, examples = count_leaks(
        _fingerprints(manifest, feature, "heldout"), _fingerprints(manifest, feature, "tuning")
    )
    if total:
        raise CorpusError(f"{total} held-out item(s) leak from tuning: " + "; ".join(examples))


def _measure(manifest: CorpusManifest, feature: str, selected: Selected, settings: object):
    """Measure each item. A file that fails its hash refuses the run (``CorpusError`` from
    ``read_verified``); any other failure of one item is counted, and its class name (never its
    message) is printed. ``MemoryError`` is not swallowed."""
    rows, errored = [], 0
    for item, note in selected:
        data = read_verified(manifest, item)
        try:
            rows.append(FEATURES[feature].measure(data, note, settings))
        except MemoryError:
            raise
        except Exception as error:  # a bad item is counted (and fails the gate), not fatal
            errored += 1
            print(f"item {item.id}: errored ({type(error).__name__})", file=sys.stderr)
    return rows, errored


def _failures(criteria: Mapping[str, str], errored: int, skipped: int) -> tuple[str, ...]:
    failed = [key for key, status in criteria.items() if status in _GATE_FAILING]
    extra = [*(["errored items"] if errored else []), *(["skipped items"] if skipped else [])]
    return (*failed, *extra)


def run_calibration(
    manifest: CorpusManifest,
    feature: str,
    split: str,
    expect_sha256: str | None = None,
    settings: object = None,
) -> CalibResult:
    """Evaluate ``feature`` on the ``split`` items of ``manifest`` and build the report bytes."""
    check_request(split, expect_sha256, gate=False)
    check_pin(manifest, expect_sha256)
    selected, skipped = _select(manifest, feature, split)
    if split == "heldout":
        check_leaks(manifest, feature)
    rows, errored = _measure(manifest, feature, selected, settings)
    measured = rounded(FEATURES[feature].aggregate(rows, settings))
    criteria = judge(feature, measured)  # type: ignore[arg-type]
    metrics = {
        "split": split,
        "counts": {"n": len(selected), "skipped": skipped, "errored": errored},
        feature: measured,
        "criteria": criteria,
    }
    report = serialise_report(build_report(manifest, metrics))
    pending = tuple(key for key, status in criteria.items() if status == NOT_APPLICABLE)
    return CalibResult(report, errored, _failures(criteria, errored, skipped), pending)


def resolve_out(
    feature: str, manifest: CorpusManifest, out: Path | None, env: Mapping[str, str]
) -> Path:
    """``out`` or the cache default, refused inside the corpus directory or the checkout."""
    if out is None:
        cache = env.get("XDG_CACHE_HOME")
        if cache and not Path(cache).is_absolute():
            raise ManifestError("XDG_CACHE_HOME must be an absolute path")
        base = Path(cache) if cache else Path(env.get("HOME") or Path.home()) / ".cache"
        out = base / "fastfoto-linux" / "calibration-eval" / feature / manifest.sha256[:12]
    resolved = out.expanduser().resolve()
    if manifest.root is None:
        raise CorpusError("the manifest has no directory")
    check_out_allowed(resolved, [manifest.root])
    return resolved


def write_report(manifest: CorpusManifest, out_dir: Path, report: bytes) -> Path:
    """Write ``report.json`` into a new run directory under ``out_dir``; returns that directory."""
    if manifest.root_fd is None:
        raise CorpusError("the manifest is closed")
    info = os.fstat(manifest.root_fd)
    name = write_outputs(
        out_dir, {REPORT: report.decode("ascii")}, forbidden=[(info.st_dev, info.st_ino)]
    )
    return out_dir / name
