"""report.json, summary.md, perf.json and the gate verdict."""

import json
from dataclasses import dataclass

from fastfoto_linux.enhance import redeye
from fastfoto_linux.evaluation.redeye_manifest import CATEGORIES, Manifest
from fastfoto_linux.evaluation.redeye_match import COLLATERAL_MARGIN, MATCH_IOD_FRACTION
from fastfoto_linux.evaluation.redeye_run import EVAL_VERSION, ImageResult, RunResult
from fastfoto_linux.evaluation.stats import nearest_rank, proportion

FLOAT_PLACES = 6
MAX_LISTED_ERRORS = 10
PEAK_LABEL = "Python/numpy allocations; excludes OpenCV-internal memory"
RSS_LABEL = "process high-water"


@dataclass(frozen=True)
class GateOptions:
    expect_sha256: str
    min_precision: float | None = None
    min_recall: float | None = None


@dataclass(frozen=True)
class GateResult:
    passed: bool
    failures: tuple[str, ...]


def _constants() -> dict[str, float]:
    return {
        name: value
        for name, value in sorted(vars(redeye).items())
        if name.isupper() and type(value) in (int, float)
    }


def _row(result: ImageResult) -> dict[str, object]:
    if result.error:
        return {"id": result.id, "sha256_12": result.sha12, "error": result.error}
    return {
        "id": result.id,
        "sha256_12": result.sha12,
        "error": None,
        "red_eyes": result.red_eyes,
        "predictions": result.predictions,
        "tp": result.tp,
        "fp_non_red": result.fp_non_red,
        "fp_unmatched": result.fp_unmatched,
        "fn": result.fn,
        "faces": {
            "found": result.found,
            "skipped_score": result.skipped_score,
            "skipped_small": result.skipped_small,
            "missed": result.missed,
        },
        "abstained_eyes": result.abstained,
        "changed_pixels": result.changed,
        "locality_pixels": result.locality,
        "damage_pixels": result.damage,
        "collateral_pixels": result.collateral,
        "negative_image": result.negative_image,
        "categories": list(result.categories),
        "damaged_categories": list(result.damaged_categories),
        "iou": list(result.ious),
    }


def _categories(ok: list[ImageResult]) -> dict[str, object]:
    table = {}
    for category in CATEGORIES:
        in_category = [r for r in ok if category in r.categories]
        damaged = sum(1 for r in in_category if category in r.damaged_categories)
        table[category] = {
            "images": len(in_category),
            "damaged": proportion(damaged, len(in_category)),
        }
    return table


def build_report(manifest: Manifest, run: RunResult) -> dict[str, object]:
    """The deterministic report: totals, per-category rows and per-image rows."""
    ok = [r for r in run.results if r.error is None]

    def total(field: str) -> int:
        # Errored items count their labelled eyes and faces: they never shrink a denominator.
        return sum(getattr(r, field) for r in run.results)

    negatives = [r for r in ok if r.negative_image]
    faces = sum(
        total(k) for k in ("found", "skipped_score", "skipped_small", "missed", "unevaluated_faces")
    )
    with_red = [r for r in run.results if r.red_eyes]
    ious = [v for r in ok for v in r.ious]
    totals = {
        "images": len(ok),
        "errored": len(run.results) - len(ok),
        "red_eyes": total("red_eyes"),
        "predictions": total("predictions"),
        "tp": total("tp"),
        "fp_non_red": total("fp_non_red"),
        "fp_unmatched": total("fp_unmatched"),
        "fn": total("fn"),
        "precision": proportion(total("tp"), total("predictions")),
        "recall": proportion(total("tp"), total("red_eyes")),
        "image_recall_any": proportion(sum(1 for r in with_red if r.tp), len(with_red)),
        "faces": {
            "total": faces,
            **{
                k: proportion(total(k), faces)
                for k in ("found", "skipped_score", "skipped_small", "missed")
            },
            "unevaluated": proportion(total("unevaluated_faces"), faces),
        },
        "abstained_eyes": total("abstained"),
        "negative_images": len(negatives),
        "damaged_negative_images": proportion(
            sum(1 for r in negatives if r.damage), len(negatives)
        ),
        "damage_pixels": total("damage"),
        "locality_pixels": total("locality"),
        "collateral_pixels": total("collateral"),
        "iou": {
            "n": len(ious),
            **{f"p{p}": nearest_rank(ious, p) for p in (10, 50, 90)},
        },
    }
    return {
        "eval_version": EVAL_VERSION,
        "manifest_sha256": manifest.sha256,
        "split": run.split,
        "match": {"iod_fraction": MATCH_IOD_FRACTION, "collateral_margin": COLLATERAL_MARGIN},
        "constants": _constants(),
        "totals": totals,
        "categories": _categories(ok),
        "images": [_row(r) for r in run.results],
    }


def _rounded(value: object) -> object:
    if isinstance(value, float):
        return round(value, FLOAT_PLACES)
    if isinstance(value, dict):
        return {k: _rounded(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_rounded(v) for v in value]
    return value


def _dump(data: object) -> str:
    return json.dumps(_rounded(data), sort_keys=True, indent=2, allow_nan=False) + "\n"


def report_json(report: dict[str, object]) -> str:
    return _dump(report)


def _pct(value: object) -> str:
    return f"{float(value) * 100:.1f}%"  # type: ignore[arg-type]


def _describe(row: dict[str, object], what: str) -> str:
    if not row["n"]:
        return f"{what}: no samples"
    text = (
        f"{what}: {row['k']} of {row['n']} ({_pct(row['p'])}); "
        f"95% Wilson interval {_pct(row['lo'])} to {_pct(row['hi'])}"
    )
    if row["zero_upper_bound"] is not None:
        text += f"; 95% upper bound {_pct(row['zero_upper_bound'])}"
    return text


def _damage_line(totals: dict, split: str) -> str:
    row = totals["damaged_negative_images"]
    kind = "frozen negatives" if split == "heldout" else "negatives"
    if not row["n"]:
        return "Negative images: no samples"
    if row["k"] == 0:
        return (
            f"No damaging change observed in {row['n']} {kind} "
            f"(95% upper bound {_pct(row['zero_upper_bound'])})"
        )
    return _describe(row, "Negative images damaged")


def render_summary(report: dict[str, object]) -> str:
    """A short Markdown summary derived only from ``report``."""
    totals: dict = report["totals"]  # type: ignore[assignment]
    faces = totals["faces"]
    iou = totals["iou"]
    lines = [
        f"# Red-eye evaluation: {report['split']} split",
        "",
        f"Manifest {str(report['manifest_sha256'])[:12]}, "
        f"harness version {report['eval_version']}, match tolerance "
        f"{MATCH_IOD_FRACTION:.2f} of the inter-ocular distance.",
        "This is output of a measuring instrument; it says nothing beyond its sample sizes.",
        "",
        f"Images evaluated: {totals['images']}; errored: {totals['errored']}",
    ]
    errors = [r for r in report["images"] if r["error"]]  # type: ignore[union-attr]
    lines += [f"- {r['id']}: {r['error']}" for r in errors[:MAX_LISTED_ERRORS]]
    lines += [
        "",
        f"Red eyes: {totals['red_eyes']}; predictions: {totals['predictions']}; "
        f"non-red-eye matches: {totals['fp_non_red']}; "
        f"unmatched predictions: {totals['fp_unmatched']}",
        _describe(totals["precision"], "Per-eye precision"),
        _describe(totals["recall"], "Per-eye recall"),
        _describe(totals["image_recall_any"], "Images with at least one red eye corrected"),
        f"Faces in the ground truth: {faces['total']}",
        *(
            _describe(faces[k], f"- {k.replace('_', ' ')}")
            for k in ("found", "skipped_score", "skipped_small", "missed", "unevaluated")
        ),
        f"Red eyes abstained in found faces (reported, not errors): {totals['abstained_eyes']}",
        "Intervals treat eyes, faces and photos as independent, so they are optimistic for "
        "correlated data such as rescans of one print.",
        "Gate G1 covers labelled negative regions and negative images only; non-red-eye matches "
        "are reported but ungated.",
        "",
        _damage_line(totals, str(report["split"])),
        f"Changed pixels outside the correction support (must be 0): {totals['locality_pixels']}",
        f"Damaging changed pixels: {totals['damage_pixels']}",
        f"Collateral changed pixels, informational only: {totals['collateral_pixels']}",
    ]
    if iou["n"]:
        lines.append(
            f"Mask overlap (IoU) over {iou['n']} matches: median {iou['p50']:.3f}, "
            f"p10 {iou['p10']:.3f}, p90 {iou['p90']:.3f}"
        )
    else:
        lines.append("Mask overlap (IoU): no samples")
    lines += ["", "| Category | Images | Damaged |", "| --- | --- | --- |"]
    for name, row in report["categories"].items():  # type: ignore[union-attr]
        damaged = row["damaged"]
        lines.append(
            f"| {name} | {row['images']} | {damaged['k'] if damaged['n'] else 'no samples'} |"
        )
    return "\n".join(lines) + "\n"


def perf_json(run: RunResult) -> str:
    """Timings and memory: useful, but not deterministic, so kept out of report.json."""
    walls = [row.wall_s for row in run.perf]
    return _dump(
        {
            "deterministic": False,
            "peak_bytes_label": PEAK_LABEL,
            "ru_maxrss_kib": run.ru_maxrss_kib,
            "ru_maxrss_label": RSS_LABEL,
            "timing": {
                "unit": "seconds",
                "note": "not deterministic",
                "p50": nearest_rank(walls, 50),
                "p95": nearest_rank(walls, 95),
            },
            "images": [
                {
                    "id": r.id,
                    "pixels": r.pixels,
                    "dpi": r.dpi,
                    "wall_s": r.wall_s,
                    "peak_bytes": r.peak_bytes,
                }
                for r in run.perf
            ],
        }
    )


def _lower(report_row: dict) -> float | None:
    return report_row["lo"]


def evaluate_gate(report: dict[str, object], options: GateOptions) -> GateResult:
    """G1 no damage, G2 locality, G3 held-out split, G4 no errors, G5 enough data."""
    totals: dict = report["totals"]  # type: ignore[assignment]
    failures: list[str] = []
    if report["manifest_sha256"] != options.expect_sha256:
        failures.append("manifest hash differs from the expected hash")
    if totals["damaged_negative_images"]["k"] or totals["damage_pixels"]:
        failures.append("G1: damaging change on the negative set")
    if totals["locality_pixels"]:
        failures.append("G2: pixels changed outside the correction support")
    if report["split"] != "heldout":
        failures.append("G3: the gate needs the held-out split")
    if totals["errored"]:
        failures.append("G4: some items errored")
    if totals["negative_images"] < 1 or totals["red_eyes"] < 1:
        failures.append("G5: insufficient data (needs a negative image and a red eye)")
    for name, floor in (("precision", options.min_precision), ("recall", options.min_recall)):
        lower = _lower(totals[name])
        if floor is not None and (lower is None or lower < floor):
            failures.append(f"{name} lower bound is below {floor}")
    return GateResult(not failures, tuple(failures))
