"""Review fixes: fail-closed leakage, bounded geometry, honest denominators, safer decoding."""

import hashlib
import io
import json
import os
import tracemalloc

import numpy as np
import pytest
from PIL import Image

from fastfoto_linux.enhance.faces import Face
from fastfoto_linux.enhance.redeye import EyeFix
from fastfoto_linux.evaluation import redeye_run
from fastfoto_linux.evaluation.redeye_images import ImageError, load_image
from fastfoto_linux.evaluation.redeye_manifest import (
    GtEye,
    GtFace,
    ManifestError,
    load_manifest,
    parse_manifest,
)
from fastfoto_linux.evaluation.redeye_match import count_faces, mask_iou
from fastfoto_linux.evaluation.redeye_output import resolve_out_dir, write_outputs
from fastfoto_linux.evaluation.redeye_report import build_report, render_summary
from fastfoto_linux.evaluation.redeye_run import evaluate_image, predict, run_eval
from tests.redeye_eval.synth import (
    KeyedDetector,
    SynthItem,
    clean_heldout_set,
    manifest_dict,
    positive,
    with_split,
    write_corpus,
)

pytestmark = pytest.mark.usefixtures("outside_checkout")


def _manifest_with_eye(**eye) -> bytes:
    data = manifest_dict([positive("a")], default="tuning")
    data["images"][0]["faces"][0]["eyes"][0].update(eye)
    return json.dumps(data).encode()


@pytest.mark.parametrize(
    "eye", [{"r": 10001.0}, {"r": 1e200}, {"x": 2e7}, {"y": -2e7}, {"r": 50000}]
)
def test_eye_geometry_has_numeric_bounds(eye) -> None:
    with pytest.raises(ManifestError):
        parse_manifest(_manifest_with_eye(**eye), None)  # type: ignore[arg-type]


def test_the_largest_allowed_eye_is_accepted() -> None:
    parse_manifest(_manifest_with_eye(r=10000.0, x=1e7), None)  # type: ignore[arg-type]


def test_mask_iou_clips_a_huge_disc_to_the_image() -> None:
    mask = np.ones((21, 21), dtype=bool)
    fix = EyeFix((90, 90, 111, 111), mask, (100.0, 100.0))
    tracemalloc.start()
    try:
        iou = mask_iou(fix, GtEye(100.0, 100.0, 10000.0, True), (240, 320))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert 0.0 < iou < 0.01
    assert peak < 5_000_000


def _only(tmp_path, synth, **kw):
    path = write_corpus(tmp_path / synth.id, [synth], default="tuning")
    return run_eval(
        load_manifest(path), "tuning", detector=KeyedDetector([synth]), perf=False, **kw
    )


def test_eyes_and_boxes_outside_the_decoded_image_are_a_per_item_error(tmp_path) -> None:
    eye_out = positive("eye-out")
    eye_out.faces[0]["eyes"][0]["x"] = 5000.0
    box_out = positive("box-out")
    box_out.negatives.append({"category": "lips", "box": [0, 0, 9000, 9000]})
    for synth in (eye_out, box_out):
        assert _only(tmp_path, synth).results[0].error == "bad_geometry"


@pytest.mark.parametrize("failure", [MemoryError, OverflowError])
def test_resource_failures_become_counted_item_errors(tmp_path, monkeypatch, failure) -> None:
    def boom(*args, **kwargs):
        raise failure

    monkeypatch.setattr(redeye_run, "evaluate_image", boom)
    result = _only(tmp_path, positive("a"))
    assert [(r.error, r.red_eyes, r.fn) for r in result.results] == [("resource", 2, 2)]


def test_errored_items_keep_their_labelled_eyes_in_the_denominators(tmp_path) -> None:
    items = clean_heldout_set()
    manifest = load_manifest(write_corpus(tmp_path / "c", items))
    (tmp_path / "c" / f"{items[0].id}.png").unlink()
    run = run_eval(manifest, "heldout", detector=KeyedDetector(items), perf=False)
    totals = build_report(manifest, run)["totals"]
    assert (totals["recall"]["k"], totals["recall"]["n"]) == (2, 4)  # type: ignore[index]
    assert totals["faces"]["unevaluated"]["k"] == 1  # type: ignore[index]
    assert totals["faces"]["total"] == 4  # type: ignore[index]
    assert totals["errored"] == 1  # type: ignore[index]


def test_path_problems_share_one_reported_reason(tmp_path) -> None:
    items = [positive("gone"), positive("bad-hash", centre=(150, 100))]
    path = write_corpus(tmp_path / "c", items, default="tuning")
    (tmp_path / "c" / "gone.png").unlink()
    (tmp_path / "c" / "bad-hash.png").write_bytes(items[0].png())
    run = run_eval(load_manifest(path), "tuning", detector=KeyedDetector(items), perf=False)
    assert {r.error for r in run.results} == {"unreadable"}


def test_tuning_images_that_cannot_be_read_fail_the_heldout_run_closed(tmp_path) -> None:
    held = with_split(positive("held"), "heldout")
    tune = with_split(positive("tune", centre=(150, 100)), "tuning")
    path = write_corpus(tmp_path / "c", [held, tune])
    (tmp_path / "c" / "tune.png").write_bytes(b"not an image")
    manifest = load_manifest(path)
    with pytest.raises(ManifestError, match="tune"):
        run_eval(manifest, "heldout", detector=KeyedDetector([held]), perf=False)


def test_a_tuning_manifest_image_that_cannot_be_read_also_fails_closed(tmp_path) -> None:
    held = with_split(positive("held"), "heldout")
    other = SynthItem("other", positive("o", centre=(150, 100)).arr, [], [], [])
    main = load_manifest(write_corpus(tmp_path / "m", [held]))
    side = load_manifest(write_corpus(tmp_path / "t", [other], default="tuning"))
    (tmp_path / "t" / "other.png").unlink()
    with pytest.raises(ManifestError, match="other"):
        run_eval(
            main, "heldout", detector=KeyedDetector([held]), tuning_manifests=[side], perf=False
        )


def _save(tmp_path, name, image, **kwargs) -> tuple[str, str]:

    buffer = io.BytesIO()
    image.save(buffer, **kwargs)
    (tmp_path / name).write_bytes(buffer.getvalue())
    return name, hashlib.sha256(buffer.getvalue()).hexdigest()


def test_only_png_jpeg_and_tiff_are_decoded(tmp_path) -> None:
    for name, kind in (("a.bmp", "BMP"), ("a.gif", "GIF"), ("a.ppm", "PPM")):
        n, sha = _save(tmp_path, name, Image.new("RGB", (8, 8)), format=kind)
        with pytest.raises(ImageError) as info:
            load_image(tmp_path, n, sha)
        assert info.value.code == "bad_format"
    for name, kind in (("a.jpg", "JPEG"), ("a.tif", "TIFF")):
        n, sha = _save(tmp_path, name, Image.new("RGB", (8, 8)), format=kind)
        assert load_image(tmp_path, n, sha).shape == (8, 8, 3)


def test_multi_frame_images_are_refused(tmp_path) -> None:
    frames = [Image.new("RGB", (8, 8), c) for c in ((1, 2, 3), (4, 5, 6))]
    n, sha = _save(
        tmp_path, "m.tif", frames[0], format="TIFF", save_all=True, append_images=frames[1:]
    )
    with pytest.raises(ImageError) as info:
        load_image(tmp_path, n, sha)
    assert info.value.code == "multi_frame"


def test_a_run_over_its_image_budget_is_refused_before_reading(tmp_path, monkeypatch) -> None:
    items = [positive("a"), positive("b", centre=(150, 100)), positive("c", centre=(140, 100))]
    manifest = load_manifest(write_corpus(tmp_path / "c", items, default="tuning"))
    monkeypatch.setattr(redeye_run, "MAX_RUN_IMAGES", 2)
    with pytest.raises(ManifestError, match="budget"):
        run_eval(manifest, "tuning", detector=KeyedDetector(items), perf=False)


def test_a_run_over_its_pixel_budget_counts_tuning_images_too(tmp_path, monkeypatch) -> None:
    held = with_split(positive("held"), "heldout")
    tune = with_split(positive("tune", centre=(150, 100)), "tuning")
    manifest = load_manifest(write_corpus(tmp_path / "c", [held, tune]))
    one = held.arr.shape[0] * held.arr.shape[1]
    monkeypatch.setattr(redeye_run, "MAX_RUN_PIXELS", 2 * one - 1)
    with pytest.raises(ManifestError, match="budget"):
        run_eval(manifest, "heldout", detector=KeyedDetector([held]), perf=False)
    monkeypatch.setattr(redeye_run, "MAX_RUN_PIXELS", 2 * one)
    run_eval(manifest, "heldout", detector=KeyedDetector([held]), perf=False)


def test_detection_runs_once_per_prediction() -> None:
    synth = positive("a")
    detector = KeyedDetector([synth])
    predict(synth.arr, 300, detector)
    assert detector.calls == 1


def test_face_matching_accepts_the_eyes_in_either_order(tmp_path) -> None:
    synth = positive("swap")
    swapped = tuple(reversed(synth.detections[0].landmarks[:2]))
    face = synth.detections[0]
    synth.detections[:] = [
        Face(face.x, face.y, face.width, face.height, (*swapped, *face.landmarks[2:]), face.score)
    ]
    manifest = load_manifest(write_corpus(tmp_path / "c", [synth], default="tuning"))
    result = evaluate_image(synth.arr, manifest.images[0], KeyedDetector([synth]))
    assert result.found == 1 and result.missed == 0
    gt = GtFace("a", (GtEye(120.0, 100.0, 5.0, True), GtEye(200.0, 100.0, 5.0, True)))
    assert count_faces([gt], [synth.detections[0]], [synth.detections[0]], []).found == 1


def test_image_level_recall_is_reported(tmp_path) -> None:
    items = clean_heldout_set()
    manifest = load_manifest(write_corpus(tmp_path / "c", items))
    run = run_eval(manifest, "heldout", detector=KeyedDetector(items), perf=False)
    row = build_report(manifest, run)["totals"]["image_recall_any"]  # type: ignore[index]
    assert (row["k"], row["n"]) == (2, 2)


def test_the_summary_states_its_statistical_limits(tmp_path) -> None:
    items = clean_heldout_set()
    manifest = load_manifest(write_corpus(tmp_path / "c", items))
    run = run_eval(manifest, "heldout", detector=KeyedDetector(items), perf=False)
    summary = render_summary(build_report(manifest, run))
    assert "independent" in summary and "ungated" in summary
    assert len(summary.splitlines()) <= 60


def test_manifest_fifo_does_not_hang(tmp_path) -> None:
    os.mkfifo(tmp_path / "m.json")
    with pytest.raises(ManifestError, match="regular"):
        load_manifest(tmp_path / "m.json")


def test_created_output_parents_are_private(tmp_path) -> None:
    out = tmp_path / "a" / "b" / "c"
    write_outputs(out, {"x": "1"})
    for directory in (out, out.parent, out.parent.parent):
        assert (directory.stat().st_mode & 0o777) == 0o700


def test_a_relative_cache_home_is_refused(tmp_path) -> None:
    manifest = load_manifest(write_corpus(tmp_path / "c", [positive("a")]))
    with pytest.raises(ManifestError, match="absolute"):
        resolve_out_dir(manifest, None, {"XDG_CACHE_HOME": "relative/cache"})
