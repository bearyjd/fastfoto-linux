"""Run the auto red-eye path over a manifest and collect per-image results."""

import resource
import time
import tracemalloc
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from fastfoto_linux.enhance.faces import Face, FaceDetector
from fastfoto_linux.enhance.fullres import detect_faces_full_res
from fastfoto_linux.enhance.redeye import EyeFix, apply_fixes, eligible_faces, find_red_eyes
from fastfoto_linux.evaluation import redeye_images
from fastfoto_linux.evaluation.redeye_manifest import Manifest, ManifestError, ManifestImage
from fastfoto_linux.evaluation.redeye_match import (
    count_changes,
    count_faces,
    fix_centroid,
    mask_iou,
    match_eyes,
)
from fastfoto_linux.evaluation.redeye_split import (
    Fingerprint,
    find_leaks,
    pixel_digest,
)

EVAL_VERSION = 1
# One run decodes at most this many images and pixels, tuning images included.
MAX_RUN_IMAGES = 20_000
MAX_RUN_PIXELS = 2_000_000_000


@dataclass(frozen=True)
class ImageResult:
    id: str
    sha12: str
    error: str | None
    red_eyes: int = 0
    predictions: int = 0
    tp: int = 0
    fp_non_red: int = 0
    fp_unmatched: int = 0
    fn: int = 0
    found: int = 0
    skipped_score: int = 0
    skipped_small: int = 0
    missed: int = 0
    abstained: int = 0
    changed: int = 0
    locality: int = 0
    damage: int = 0
    collateral: int = 0
    negative_image: bool = False
    categories: tuple[str, ...] = ()
    damaged_categories: tuple[str, ...] = ()
    ious: tuple[float, ...] = ()


@dataclass(frozen=True)
class PerfRow:
    id: str
    pixels: int
    dpi: int
    wall_s: float
    peak_bytes: int | None


@dataclass(frozen=True)
class RunResult:
    split: str
    results: tuple[ImageResult, ...]
    perf: tuple[PerfRow, ...]
    ru_maxrss_kib: int


@dataclass(frozen=True)
class Prediction:
    fixes: tuple[EyeFix, ...]
    eligible: tuple[Face, ...]
    detected: tuple[Face, ...]


def predict(img: np.ndarray, dpi: int, detector: FaceDetector | None) -> Prediction:
    """What the auto red-eye path finds in ``img`` (``detect_fixes``), and the faces behind it."""
    eligible = eligible_faces(img, dpi, detector)
    return Prediction(
        find_red_eyes(img, eligible), eligible, tuple(detect_faces_full_res(img, detector))
    )


def evaluate_image(
    img: np.ndarray, item: ManifestImage, detector: FaceDetector | None
) -> ImageResult:
    """Score one image: matching, face accounting and changed-pixel accounting."""
    prediction = predict(img, item.dpi, detector)
    out = apply_fixes(img, prediction.fixes)
    match = match_eyes([fix_centroid(f) for f in prediction.fixes], item.faces)
    red_eyes = sum(eye.red for face in item.faces for eye in face.eyes)
    negative_image = red_eyes == 0
    faces = count_faces(item.faces, prediction.detected, prediction.eligible, match.fn)
    changes = count_changes(
        img, out, prediction.fixes, item.faces, item.negatives, negative_image=negative_image
    )
    ious = tuple(
        mask_iou(prediction.fixes[m.pred], item.faces[m.face].eyes[m.eye]) for m in match.tp
    )
    categories = tuple(sorted({r.category for r in item.negatives})) or (
        ("other",) if negative_image else ()
    )
    return ImageResult(
        id=item.id,
        sha12=item.sha256[:12],
        error=None,
        red_eyes=red_eyes,
        predictions=len(prediction.fixes),
        tp=len(match.tp),
        fp_non_red=len(match.fp_non_red),
        fp_unmatched=len(match.fp_unmatched),
        fn=len(match.fn),
        found=faces.found,
        skipped_score=faces.skipped_score,
        skipped_small=faces.skipped_small,
        missed=faces.missed,
        abstained=faces.abstained,
        changed=changes.changed,
        locality=changes.locality,
        damage=changes.damage,
        collateral=changes.collateral,
        negative_image=negative_image,
        categories=categories,
        damaged_categories=changes.damaged_categories,
        ious=ious,
    )


def _timed(
    img: np.ndarray, item: ManifestImage, detector: FaceDetector | None, perf: bool
) -> tuple[ImageResult, PerfRow | None]:
    start = time.perf_counter()
    result = evaluate_image(img, item, detector)
    wall = time.perf_counter() - start
    if not perf:
        return result, None
    tracemalloc.start()
    try:
        evaluate_image(img, item, detector)  # a second pass: tracing slows the first
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    return result, PerfRow(item.id, int(img.shape[0] * img.shape[1]), item.dpi, wall, peak)


def _fingerprint(item: ManifestImage, img: np.ndarray | None) -> Fingerprint:
    pixel = None if img is None else pixel_digest(img)
    return Fingerprint(item.id, item.sha256, pixel, item.group)


def _tuning_fingerprints(manifest: Manifest, items: Sequence[ManifestImage]) -> list[Fingerprint]:
    prints = []
    for item in items:
        try:
            img = redeye_images.load_image(manifest.root, item.path, item.sha256)
        except redeye_images.ImageError:
            img = None
        prints.append(_fingerprint(item, img))
    return prints


def run_eval(
    manifest: Manifest,
    split: str,
    *,
    detector: FaceDetector | None = None,
    tuning_manifests: Sequence[Manifest] = (),
    perf: bool = True,
) -> RunResult:
    """Evaluate every image of ``split``; a held-out run is refused if it leaks from tuning."""
    results: list[ImageResult] = []
    rows: list[PerfRow] = []
    heldout_prints: list[Fingerprint] = []
    for item in (i for i in manifest.images if i.split == split):
        try:
            img = redeye_images.load_image(manifest.root, item.path, item.sha256)
        except redeye_images.ImageError as error:
            results.append(ImageResult(item.id, item.sha256[:12], error.code))
            heldout_prints.append(_fingerprint(item, None))
            continue
        heldout_prints.append(_fingerprint(item, img))
        result, row = _timed(img, item, detector, perf)
        results.append(result)
        if row is not None:
            rows.append(row)
    if split == "heldout":
        tuning = _tuning_fingerprints(manifest, [i for i in manifest.images if i.split == "tuning"])
        for other in tuning_manifests:
            tuning += _tuning_fingerprints(other, other.images)
        leaks = find_leaks(heldout_prints, tuning)
        if leaks:
            raise ManifestError("held-out split leaks from tuning: " + "; ".join(leaks[:5]))
    return RunResult(
        split, tuple(results), tuple(rows), resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    )
