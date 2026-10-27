"""Second review pass: pre-decode budgets, unevaluated negatives, resource errors, bounded leaks."""

import json
import tracemalloc

import numpy as np
import pytest
from PIL import Image

from fastfoto_linux.evaluation import redeye_images, redeye_run
from fastfoto_linux.evaluation.redeye_manifest import (
    GtEye,
    GtFace,
    ManifestError,
    Region,
    load_manifest,
)
from fastfoto_linux.evaluation.redeye_match import count_changes
from fastfoto_linux.evaluation.redeye_report import (
    GateOptions,
    build_report,
    evaluate_gate,
    perf_json,
    render_summary,
)
from fastfoto_linux.evaluation.redeye_run import ImageResult, run_eval
from fastfoto_linux.evaluation.redeye_split import Fingerprint, count_leaks, find_leaks
from tests.redeye_eval.synth import (
    KeyedDetector,
    clean_heldout_set,
    positive,
    with_split,
    write_corpus,
)

pytestmark = pytest.mark.usefixtures("outside_checkout")


def test_the_pixel_budget_is_charged_from_the_header_before_decoding(tmp_path, monkeypatch) -> None:
    items = [positive("a"), positive("b", centre=(150, 100)), positive("c", centre=(140, 100))]
    manifest = load_manifest(write_corpus(tmp_path / "c", items, default="tuning"))
    one = items[0].arr.shape[0] * items[0].arr.shape[1]
    monkeypatch.setattr(redeye_run, "MAX_RUN_PIXELS", one + one // 2)
    opened, loaded, keep = set(), set(), []  # keep: ids must not be reused
    real_open, real_load = Image.open, Image.Image.load

    def spy_open(*args, **kwargs):
        image = real_open(*args, **kwargs)
        keep.append(image)
        opened.add(id(image))
        return image

    def spy_load(self):
        if id(self) in opened:
            loaded.add(id(self))
        return real_load(self)

    monkeypatch.setattr(Image, "open", spy_open)
    monkeypatch.setattr(Image.Image, "load", spy_load)
    with pytest.raises(ManifestError, match="budget"):
        run_eval(manifest, "tuning", detector=KeyedDetector(items), perf=False)
    assert (
        len(opened) == 2 and len(loaded) == 1
    )  # the second image was refused before its pixels were decoded


def _lost_negative(tmp_path):
    items = clean_heldout_set()
    manifest = load_manifest(write_corpus(tmp_path / "c", items))
    lips = next(i for i in items if i.id.endswith("lips"))
    (tmp_path / "c" / f"{lips.id}.png").unlink()
    run = run_eval(manifest, "heldout", detector=KeyedDetector(items), perf=False)
    return manifest, build_report(manifest, run)


def test_errored_negatives_are_counted_beside_the_damage_figure(tmp_path) -> None:
    _, report = _lost_negative(tmp_path)
    totals = report["totals"]
    assert totals["unevaluated_negative_images"] == 1  # type: ignore[index]
    assert totals["damaged_negative_images"]["n"] == 7  # type: ignore[index]
    assert report["categories"]["lips"]["unevaluated"] == 1  # type: ignore[index]
    summary = render_summary(report)
    assert "1 negative image(s) unevaluated" in summary


def _flaky_loader(monkeypatch, bad: str, failure):
    real = redeye_images.load_image

    def load(root, rel, sha, charge=None):
        if rel == f"{bad}.png":
            raise failure
        return real(root, rel, sha, charge)

    monkeypatch.setattr(redeye_images, "load_image", load)


@pytest.mark.parametrize("failure", [MemoryError(), OverflowError()])
def test_a_resource_failure_while_loading_a_heldout_item_is_a_counted_error(
    tmp_path, monkeypatch, failure
) -> None:
    items = clean_heldout_set()
    manifest = load_manifest(write_corpus(tmp_path / "c", items))
    _flaky_loader(monkeypatch, items[0].id, failure)
    run = run_eval(manifest, "heldout", detector=KeyedDetector(items), perf=False)
    assert [(r.id, r.error) for r in run.results if r.error] == [(items[0].id, "resource")]
    assert build_report(manifest, run)["totals"]["errored"] == 1  # type: ignore[index]


def test_a_resource_failure_in_the_digest_is_a_counted_error(tmp_path, monkeypatch) -> None:
    items = clean_heldout_set()[:3]
    manifest = load_manifest(write_corpus(tmp_path / "c", items))

    def boom(img):
        raise MemoryError

    monkeypatch.setattr(redeye_run, "pixel_digest", boom)
    run = run_eval(manifest, "heldout", detector=KeyedDetector(items), perf=False)
    assert {r.error for r in run.results} == {"resource"}


def test_a_resource_failure_on_a_tuning_item_is_a_controlled_refusal(tmp_path, monkeypatch) -> None:
    held = with_split(positive("held"), "heldout")
    tune = with_split(positive("tune", centre=(150, 100)), "tuning")
    manifest = load_manifest(write_corpus(tmp_path / "c", [held, tune]))
    _flaky_loader(monkeypatch, "tune", MemoryError())
    with pytest.raises(ManifestError, match=r"tune.*resource"):
        run_eval(manifest, "heldout", detector=KeyedDetector([held]), perf=False)


def test_a_tuning_path_problem_reports_only_the_collapsed_reason(tmp_path) -> None:
    held = with_split(positive("held"), "heldout")
    tune = with_split(positive("tune", centre=(150, 100)), "tuning")
    manifest = load_manifest(write_corpus(tmp_path / "c", [held, tune]))
    (tmp_path / "c" / "tune.png").unlink()
    with pytest.raises(ManifestError, match="unreadable") as info:
        run_eval(manifest, "heldout", detector=KeyedDetector([held]), perf=False)
    assert "missing" not in str(info.value)


def test_a_failing_profiling_pass_keeps_the_first_pass_scores(tmp_path, monkeypatch) -> None:
    item = positive("p")
    manifest = load_manifest(write_corpus(tmp_path / "c", [item], default="tuning"))
    scored = ImageResult(
        "p",
        "x" * 12,
        None,
        red_eyes=2,
        predictions=3,
        tp=2,
        fp_unmatched=1,
        negative_image=False,
        damage=1,
    )
    calls = iter([scored, MemoryError()])

    def fake(img, it, detector):
        outcome = next(calls)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(redeye_run, "evaluate_image", fake)
    run = run_eval(manifest, "tuning", detector=KeyedDetector([item]), perf=True)
    assert run.results[0] is scored and run.results[0].error is None
    assert run.perf[0].error == "resource" and run.perf[0].peak_bytes is None
    assert json.loads(perf_json(run))["images"][0]["error"] == "resource"


def test_leak_search_is_linear_in_memory_and_keeps_the_total() -> None:
    held = [Fingerprint(f"h{i}", f"{i:064x}", f"p{i}", "same") for i in range(500)]
    tune = [Fingerprint(f"t{i}", f"{i + 1000:064x}", f"q{i}", "same") for i in range(500)]
    tracemalloc.start()
    try:
        total, examples = count_leaks(held, tune)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert total == 500 and len(examples) <= 5
    assert len(find_leaks(held, tune)) <= 5
    assert peak < 500_000


def test_a_negative_image_attributes_damage_per_category_box() -> None:
    img = np.zeros((40, 40, 3), dtype=np.uint8)
    out = img.copy()
    out[2, 2] = 9
    boxes = [Region("lips", (0, 0, 5, 5)), Region("red_clothing", (10, 10, 15, 15))]
    counts = count_changes(img, out, [], [], boxes, negative_image=True)
    assert counts.damage == 1
    assert counts.damaged_categories == ("lips",)
    face = GtFace("a", (GtEye(5.0, 5.0, 2.0, False), GtEye(30.0, 5.0, 2.0, False)))
    assert count_changes(img, out, [], [face], boxes, negative_image=True).damage == 1


def test_g5_counts_the_red_eyes_of_errored_items_and_g4_still_fails(tmp_path) -> None:
    items = clean_heldout_set()
    manifest = load_manifest(write_corpus(tmp_path / "c", items))
    for item in items[:2]:  # both positives
        (tmp_path / "c" / f"{item.id}.png").unlink()
    run = run_eval(manifest, "heldout", detector=KeyedDetector(items), perf=False)
    verdict = evaluate_gate(build_report(manifest, run), GateOptions(manifest.sha256))
    assert not verdict.passed
    assert any("G4" in f for f in verdict.failures)
    assert not any("G5" in f for f in verdict.failures)
