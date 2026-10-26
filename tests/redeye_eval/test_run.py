"""The runner on synthetic corpora: parity with the auto path, accounting and error rows."""

import numpy as np
import pytest

from fastfoto_linux.enhance.redeye import detect_fixes, eligible_faces, find_red_eyes
from fastfoto_linux.evaluation import redeye_images
from fastfoto_linux.evaluation.redeye_manifest import load_manifest
from fastfoto_linux.evaluation.redeye_run import evaluate_image, predict, run_eval
from tests.redeye_eval.synth import (
    PAINTERS,
    RED,
    KeyedDetector,
    SynthItem,
    clean_heldout_set,
    disc,
    negative,
    positive,
    write_corpus,
)


@pytest.fixture
def manifest_item(tmp_path):
    def build(synth):
        manifest = load_manifest(write_corpus(tmp_path / synth.id, [synth], default="tuning"))
        return manifest.images[0]

    return build


def _same_fixes(left, right) -> bool:
    return len(left) == len(right) and all(
        a.roi == b.roi and np.array_equal(a.mask, b.mask) and a.center == b.center
        for a, b in zip(left, right, strict=True)
    )


def test_eligible_faces_is_public_and_detect_fixes_is_unchanged() -> None:
    item = positive("a")
    detector = KeyedDetector([item])
    faces = eligible_faces(item.arr, 300, detector)
    assert _same_fixes(find_red_eyes(item.arr, faces), detect_fixes(item.arr, 300, detector))


@pytest.mark.parametrize("synth", [positive("p"), *(negative(f"n-{c}", c) for c in PAINTERS)])
def test_predictions_equal_detect_fixes(synth) -> None:
    detector = KeyedDetector([synth])
    prediction = predict(synth.arr, 300, detector)
    assert _same_fixes(prediction.fixes, detect_fixes(synth.arr, 300, detector))


@pytest.mark.parametrize("category", list(PAINTERS))
def test_no_negative_category_is_damaged_with_faces_placed_on_it(category, manifest_item) -> None:
    synth = negative(f"n-{category}", category)
    result = evaluate_image(synth.arr, manifest_item(synth), KeyedDetector([synth]))
    assert (result.damage, result.locality, result.predictions) == (0, 0, 0)
    assert result.negative_image and result.error is None
    assert result.categories == (category,)


def test_precision_and_recall_counts_match_the_painted_truth(manifest_item) -> None:
    both = positive("both")
    one = positive("one", red=(True, False))
    for synth, expected in ((both, (2, 2, 0, 0)), (one, (1, 1, 0, 0))):
        result = evaluate_image(synth.arr, manifest_item(synth), KeyedDetector([synth]))
        assert (result.predictions, result.tp, result.fp_non_red, result.fn) == expected
        assert result.fp_unmatched == 0
        assert result.found == 1 and result.missed == 0
        assert len(result.ious) == result.tp and min(result.ious) > 0.8


def test_a_red_pupil_on_an_eye_labelled_non_red_is_a_non_red_false_positive(
    manifest_item,
) -> None:
    base = positive("lie", red=(True, False))
    painted = base.arr.copy()
    disc(painted, 200.0, 100.0, 5.0, RED)  # the second eye is labelled non-red
    lie = SynthItem("lie", painted, base.faces, [], base.detections)
    result = evaluate_image(lie.arr, manifest_item(lie), KeyedDetector([lie]))
    assert result.fp_non_red == 1 and result.tp == 1 and result.fp_unmatched == 0


def test_a_tiny_face_is_skipped_small_and_its_red_eyes_are_missed(manifest_item) -> None:
    synth = positive("tiny", iod=20, r=2.5)
    result = evaluate_image(synth.arr, manifest_item(synth), KeyedDetector([synth]))
    assert (result.skipped_small, result.found, result.predictions) == (1, 0, 0)
    assert result.fn == 2


def test_a_low_score_face_is_skipped_for_score(manifest_item) -> None:
    synth = positive("low", score=0.5)
    result = evaluate_image(synth.arr, manifest_item(synth), KeyedDetector([synth]))
    assert (result.skipped_score, result.found) == (1, 0)


def test_a_two_pixel_speck_is_abstained_not_a_false_positive(manifest_item) -> None:
    synth = positive("speck", r=1.0)
    result = evaluate_image(synth.arr, manifest_item(synth), KeyedDetector([synth]))
    assert (result.predictions, result.fp_unmatched, result.fp_non_red) == (0, 0, 0)
    assert result.abstained == 2 and result.found == 1


def test_a_face_the_detector_missed_counts_as_missed(manifest_item) -> None:
    synth = positive("blind")
    synth.detections.clear()
    result = evaluate_image(synth.arr, manifest_item(synth), KeyedDetector([synth]))
    assert (result.missed, result.fn) == (1, 2)


def test_inputs_are_not_modified(manifest_item) -> None:
    synth = positive("same")
    before = synth.arr.copy()
    synth.arr.setflags(write=False)
    evaluate_image(synth.arr, manifest_item(synth), KeyedDetector([synth]))
    assert np.array_equal(synth.arr, before)


def test_run_eval_reports_only_the_requested_split_and_counts_errors(tmp_path) -> None:
    items = clean_heldout_set()
    path = write_corpus(tmp_path / "c", items)
    (tmp_path / "c" / f"{items[0].id}.png").unlink()
    result = run_eval(load_manifest(path), "heldout", detector=KeyedDetector(items), perf=False)
    assert len(result.results) == len(items)
    errors = [r for r in result.results if r.error]
    assert [(r.id, r.error) for r in errors] == [(items[0].id, "missing")]
    assert result.perf == ()


def test_a_valid_image_just_under_the_cap_is_evaluated(tmp_path, monkeypatch) -> None:
    item = positive("big")
    shape = item.arr.shape
    monkeypatch.setattr(redeye_images, "MAX_SOURCE_PIXELS", shape[0] * shape[1])
    path = write_corpus(tmp_path / "c", [item], default="tuning")
    result = run_eval(load_manifest(path), "tuning", detector=KeyedDetector([item]), perf=False)
    assert result.results[0].error is None and result.results[0].tp == 2


def test_perf_rows_are_recorded_when_asked(tmp_path) -> None:
    item = positive("p")
    path = write_corpus(tmp_path / "c", [item], default="tuning")
    result = run_eval(load_manifest(path), "tuning", detector=KeyedDetector([item]), perf=True)
    row = result.perf[0]
    assert row.pixels == item.arr.shape[0] * item.arr.shape[1] and row.dpi == 300
    assert row.wall_s >= 0 and (row.peak_bytes or 0) > 0
    assert result.ru_maxrss_kib > 0
