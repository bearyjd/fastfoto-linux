"""report.json / summary.md determinism, wording, and the gate verdicts G1-G5."""

import json
import re

import pytest

from fastfoto_linux.evaluation.redeye_manifest import load_manifest
from fastfoto_linux.evaluation.redeye_report import (
    GateOptions,
    build_report,
    evaluate_gate,
    perf_json,
    render_summary,
    report_json,
)
from fastfoto_linux.evaluation.redeye_run import run_eval
from tests.redeye_eval.synth import (
    KeyedDetector,
    SynthItem,
    clean_heldout_set,
    negative,
    positive,
    with_split,
    write_corpus,
)

BANNED = re.compile(r"(?i)no false positives|zero false positives|100% (accurate|precision)")
UNIQUE = "uniq-dir-9f3a"


def _run(tmp_path, items, split="heldout", perf=False, name=UNIQUE):
    manifest = load_manifest(write_corpus(tmp_path / name, items))
    run = run_eval(manifest, split, detector=KeyedDetector(items), perf=perf)
    return manifest, run, build_report(manifest, run)


def _gate(manifest, report, **kw):
    return evaluate_gate(report, GateOptions(expect_sha256=manifest.sha256, **kw))


def test_reports_are_byte_identical_across_runs_and_sorted(tmp_path) -> None:
    items = clean_heldout_set()
    _, _, first = _run(tmp_path, items)
    _, _, second = _run(tmp_path, items)
    assert report_json(first) == report_json(second)
    assert render_summary(first) == render_summary(second)
    text = report_json(first)
    assert text.endswith("\n") and text.startswith("{\n  ")

    def check(pairs):
        keys = [k for k, _ in pairs]
        assert keys == sorted(keys)
        return dict(pairs)

    json.loads(text, object_pairs_hook=check)


def test_report_content_has_every_metric_with_n_and_an_interval(tmp_path) -> None:
    manifest, _, report = _run(tmp_path, clean_heldout_set())
    data = json.loads(report_json(report))
    assert data["manifest_sha256"] == manifest.sha256
    assert data["eval_version"] == 1 and data["split"] == "heldout"
    assert data["constants"]["MIN_FACE_SCORE"] == 0.9
    assert data["match"]["iod_fraction"] == 0.15
    totals = data["totals"]
    for key in ("precision", "recall", "damaged_negative_images"):
        assert {"k", "n", "lo", "hi"} <= set(totals[key])
    assert totals["damaged_negative_images"]["k"] == 0
    assert totals["damaged_negative_images"]["zero_upper_bound"] is not None
    assert set(data["categories"]) >= {
        "red_clothing",
        "lips",
        "jewelry",
        "signs",
        "flowers",
        "printed_text",
        "spectacles",
        "non_red_pupils",
        "reflections",
        "other",
    }
    assert data["categories"]["reflections"]["damaged"]["note"] == "no samples"
    assert data["categories"]["reflections"]["images"] == 0
    assert len(data["images"]) == len(clean_heldout_set())
    assert totals["iou"]["p50"] is not None


def test_summary_is_short_hedged_and_never_claims_zero_false_positives(tmp_path) -> None:
    _, _, report = _run(tmp_path, clean_heldout_set())
    summary = render_summary(report)
    assert len(summary.splitlines()) <= 60
    assert "95% upper bound" in summary
    assert "No damaging change observed in" in summary
    assert not BANNED.search(summary)


def test_reports_never_contain_paths_or_rights_source(tmp_path) -> None:
    manifest, run, report = _run(tmp_path, clean_heldout_set(), perf=True)
    blobs = [report_json(report), render_summary(report), perf_json(run)]
    for blob in blobs:
        assert UNIQUE not in blob and str(tmp_path) not in blob
        assert "generated in code" not in blob and ".png" not in blob
    assert manifest.images[0].sha256[:12] in blobs[0]


def test_perf_json_has_timings_memory_and_labels(tmp_path) -> None:
    _, run, _ = _run(tmp_path, clean_heldout_set()[:2], perf=True)
    data = json.loads(perf_json(run))
    assert data["deterministic"] is False
    assert "excludes OpenCV-internal memory" in data["peak_bytes_label"]
    assert "process high-water" in data["ru_maxrss_label"]
    assert data["images"][0]["pixels"] > 0 and data["timing"]["p95"] >= data["timing"]["p50"]


def test_clean_heldout_set_passes_the_gate(tmp_path) -> None:
    manifest, _, report = _run(tmp_path, clean_heldout_set())
    verdict = _gate(manifest, report)
    assert verdict.passed and verdict.failures == ()


def test_a_planted_damaging_negative_fails_g1(tmp_path) -> None:
    base = positive("planted")  # a red pupil pair where the labels say: nothing red here
    box = [100, 90, 220, 110]
    planted = with_split(
        SynthItem(
            "planted", base.arr, [], [{"category": "red_clothing", "box": box}], base.detections
        ),
        "heldout",
    )
    manifest, _, report = _run(tmp_path, [*clean_heldout_set(), planted])
    verdict = _gate(manifest, report)
    assert not verdict.passed and any("G1" in f for f in verdict.failures)
    assert report["totals"]["damaged_negative_images"]["k"] == 1  # type: ignore[index]
    assert report["categories"]["red_clothing"]["damaged"]["k"] >= 1  # type: ignore[index]


def test_a_wrong_manifest_hash_fails(tmp_path) -> None:
    manifest, _, report = _run(tmp_path, clean_heldout_set())
    verdict = evaluate_gate(report, GateOptions(expect_sha256="0" * 64))
    assert not verdict.passed and any("manifest" in f for f in verdict.failures)
    assert manifest.sha256 != "0" * 64


def test_an_errored_item_fails_g4_and_is_listed(tmp_path) -> None:
    items = clean_heldout_set()
    manifest = load_manifest(write_corpus(tmp_path / "c", items))
    (tmp_path / "c" / f"{items[0].id}.png").unlink()
    run = run_eval(manifest, "heldout", detector=KeyedDetector(items), perf=False)
    report = build_report(manifest, run)
    verdict = _gate(manifest, report)
    assert not verdict.passed and any("G4" in f for f in verdict.failures)
    assert "missing" in render_summary(report) and items[0].id in render_summary(report)
    assert report["totals"]["errored"] == 1  # type: ignore[index]


def _insufficient(kind: str) -> list:
    if kind == "pos":
        return [with_split(positive("only-pos"), "heldout")]
    if kind == "neg":
        return [with_split(negative("only-neg", "lips"), "heldout")]
    return []


@pytest.mark.parametrize("kind", ["empty", "pos", "neg"])
def test_insufficient_data_fails_g5(tmp_path, kind) -> None:
    items = _insufficient(kind)
    manifest, _, report = _run(tmp_path, items)
    verdict = _gate(manifest, report)
    assert not verdict.passed and any(
        "G5" in f and "insufficient data" in f for f in verdict.failures
    )
    if not items:
        assert "no samples" in render_summary(report)
        assert report["totals"]["precision"]["lo"] is None  # type: ignore[index]


def test_optional_wilson_lower_bound_gates(tmp_path) -> None:
    manifest, _, report = _run(tmp_path, clean_heldout_set())
    assert not _gate(manifest, report, min_precision=0.95).passed  # 4 of 4 has a lower bound ~0.51
    assert not _gate(manifest, report, min_recall=0.95).passed
    assert _gate(manifest, report, min_precision=0.3, min_recall=0.3).passed


def test_g_locality_violation_fails_g2() -> None:
    report = {
        "manifest_sha256": "a" * 64,
        "totals": {
            "errored": 0,
            "negative_images": 3,
            "red_eyes": 2,
            "damaged_negative_images": {"k": 0, "n": 3},
            "damage_pixels": 0,
            "locality_pixels": 7,
            "precision": {"lo": 0.5},
            "recall": {"lo": 0.5},
        },
        "split": "heldout",
    }
    verdict = evaluate_gate(report, GateOptions(expect_sha256="a" * 64))
    assert not verdict.passed and any("G2" in f for f in verdict.failures)
