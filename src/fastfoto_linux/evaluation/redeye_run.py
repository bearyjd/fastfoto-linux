"""Run the auto red-eye path over a manifest and collect per-image results."""

import contextlib
import hashlib
import logging
import resource
import time
import tracemalloc
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from fastfoto_linux.enhance.faces import Face, FaceDetector, default_detector
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
    count_leaks,
    pixel_digest,
)

logger = logging.getLogger(__name__)
EVAL_VERSION = 1
# One run decodes at most this many images and pixels, tuning images included.
MAX_RUN_IMAGES = 20_000
MAX_RUN_PIXELS = 2_000_000_000
MAX_RUN_BYTES = 4 * 1024**3


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
    unevaluated_faces: int = 0
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
    error: str | None = None


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


class _MemoDetector:
    """Answers a repeated ``detect`` call from memory: eligibility and skip accounting both
    need the faces, and detecting twice would double the cost of every image."""

    def __init__(self, detector: FaceDetector) -> None:
        self._detector = detector
        self._seen: dict[tuple[tuple[int, ...], bytes], tuple[Face, ...]] = {}

    def detect(self, img_rgb: np.ndarray) -> tuple[Face, ...]:
        data = np.ascontiguousarray(img_rgb)
        key = (data.shape, hashlib.blake2b(data, digest_size=16).digest())
        if key not in self._seen:
            self._seen[key] = tuple(self._detector.detect(data))
        return self._seen[key]


def predict(img: np.ndarray, dpi: int, detector: FaceDetector | None) -> Prediction:
    """What the auto red-eye path finds in ``img`` (``detect_fixes``), and the faces behind it."""
    memo = _MemoDetector(default_detector() if detector is None else detector)
    eligible = eligible_faces(img, dpi, memo)
    return Prediction(
        find_red_eyes(img, eligible), eligible, tuple(detect_faces_full_res(img, memo))
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
        mask_iou(prediction.fixes[m.pred], item.faces[m.face].eyes[m.eye], img.shape)
        for m in match.tp
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
    pixels = int(img.shape[0] * img.shape[1])
    tracemalloc.start()
    try:
        evaluate_image(img, item, detector)  # a second pass: tracing slows the first
        peak, error = tracemalloc.get_traced_memory()[1], None
    except (MemoryError, OverflowError):  # profiling only: the scores above stand
        peak, error = None, "resource"
    finally:
        tracemalloc.stop()
    return result, PerfRow(item.id, pixels, item.dpi, wall, peak, error)


REPORTED_PATH_PROBLEM = "unreadable"
_PATH_PROBLEMS = ("missing", "unsafe_path", "hash_mismatch")


def _error_result(item: ManifestImage, code: str) -> ImageResult:
    """An errored item keeps its labelled red eyes (as misses) and faces in the denominators."""
    red_eyes = sum(eye.red for face in item.faces for eye in face.eyes)
    negative_image = red_eyes == 0
    categories = tuple(sorted({r.category for r in item.negatives})) or (
        ("other",) if negative_image else ()
    )
    return ImageResult(
        item.id,
        item.sha256[:12],
        code,
        red_eyes=red_eyes,
        fn=red_eyes,
        unevaluated_faces=len(item.faces),
        negative_image=negative_image,
        categories=categories,
    )


def _geometry_ok(img: np.ndarray, item: ManifestImage) -> bool:
    """Every annotated eye centre and negative box lies inside the decoded image."""
    height, width = img.shape[:2]
    eyes = (eye for face in item.faces for eye in face.eyes)
    return all(0 <= e.x <= width and 0 <= e.y <= height for e in eyes) and all(
        r.box[2] <= width and r.box[3] <= height for r in item.negatives
    )


class _Budget:
    """The most decoded pixels and file bytes one run may read, tuning images included."""

    def __init__(self) -> None:
        self.pixels = 0
        self.bytes = 0

    def charge_bytes(self, size: int) -> None:
        """Called with a file's size, before its bytes are read."""
        self.bytes += size
        if self.bytes > MAX_RUN_BYTES:
            raise redeye_images.BudgetExceeded

    def charge(self, pixels: int) -> None:
        """Called with the header's pixel count, before the pixels are decoded."""
        self.pixels += pixels
        if self.pixels > MAX_RUN_PIXELS:
            raise redeye_images.BudgetExceeded


def _reported(code: str) -> str:
    return REPORTED_PATH_PROBLEM if code in _PATH_PROBLEMS else code


def _load(
    root: redeye_images.PinnedRoot, item: ManifestImage, digests: dict[str, str], budget: _Budget
) -> np.ndarray:
    """Load ``item`` (charging the budget from its header first) and remember its pixel digest.

    The digest cache is keyed by file sha256: the loader verified the bytes against it, and equal
    bytes decode to equal pixels, so a cached digest is the digest.
    """
    try:
        img = redeye_images.load_image(
            root, item.path, item.sha256, budget.charge, budget.charge_bytes
        )
    except redeye_images.BudgetExceeded as error:
        raise ManifestError("the run exceeds its pixel or byte budget") from error
    digests[item.sha256] = pixel_digest(img)
    return img


def _tuning_fingerprints(
    root: redeye_images.PinnedRoot,
    items: Sequence[ManifestImage],
    digests: dict[str, str],
    budget: _Budget,
) -> list[Fingerprint]:
    """Fingerprints of tuning items. One that cannot be read refuses the run: leakage
    evidence must never disappear because a file is missing or damaged."""
    prints = []
    for item in items:
        if item.sha256 not in digests:
            try:
                _load(root, item, digests, budget)
            except (redeye_images.ImageError, MemoryError, OverflowError) as error:
                code = error.code if isinstance(error, redeye_images.ImageError) else "resource"
                raise ManifestError(
                    f"tuning image {item.id!r} cannot be read ({_reported(code)}), "
                    "so leakage cannot be ruled out"
                ) from error
        prints.append(Fingerprint(item.id, item.sha256, digests[item.sha256], item.group))
    return prints


def _evaluate_loaded(
    img: np.ndarray, item: ManifestImage, detector: FaceDetector | None, perf: bool
) -> tuple[ImageResult, PerfRow | None]:
    if not _geometry_ok(img, item):
        return _error_result(item, "bad_geometry"), None
    try:
        return _timed(img, item, detector, perf)
    except (MemoryError, OverflowError) as error:
        logger.debug("image %s: %s", item.id, type(error).__name__)
        return _error_result(item, "resource"), None


def run_eval(
    manifest: Manifest,
    split: str,
    *,
    detector: FaceDetector | None = None,
    tuning_manifests: Sequence[Manifest] = (),
    perf: bool = True,
) -> RunResult:
    """Evaluate every image of ``split``; a held-out run is refused if it leaks from tuning."""
    selected = [i for i in manifest.images if i.split == split]
    tuning_items = [i for i in manifest.images if i.split == "tuning"] if split == "heldout" else []
    planned = len(selected) + len(tuning_items)
    planned += sum(len(m.images) for m in tuning_manifests) if split == "heldout" else 0
    if planned > MAX_RUN_IMAGES:
        raise ManifestError("the run exceeds its image budget")
    with contextlib.ExitStack() as stack:  # roots are pinned once; reads never reopen the path
        root = stack.enter_context(_pin(manifest))
        others = [(stack.enter_context(_pin(m)), m) for m in tuning_manifests]
        return _run_pinned(split, (selected, tuning_items), (root, others), (detector, perf))


def _pin(manifest: Manifest) -> redeye_images.PinnedRoot:
    """The manifest's own directory descriptor when it has one, else its path, opened now."""
    try:
        return redeye_images.PinnedRoot(
            manifest.root if manifest.root_fd is None else manifest.root_fd
        )
    except redeye_images.ImageError as error:
        raise ManifestError("cannot open a corpus directory") from error


def _run_pinned(
    split: str,
    plan: tuple[list[ManifestImage], list[ManifestImage]],
    roots: tuple[redeye_images.PinnedRoot, Sequence[tuple[redeye_images.PinnedRoot, Manifest]]],
    options: tuple[FaceDetector | None, bool],
) -> RunResult:
    selected, tuning_items = plan
    root, others = roots
    detector, perf = options
    budget = _Budget()
    digests: dict[str, str] = {}
    results: list[ImageResult] = []
    rows: list[PerfRow] = []
    heldout_prints: list[Fingerprint] = []
    for item in selected:
        try:
            img = _load(root, item, digests, budget)
        except (redeye_images.ImageError, MemoryError, OverflowError) as error:
            code = error.code if isinstance(error, redeye_images.ImageError) else "resource"
            logger.debug("image %s: %s", item.id, code)
            results.append(_error_result(item, _reported(code)))
            heldout_prints.append(Fingerprint(item.id, item.sha256, None, item.group))
            continue
        heldout_prints.append(Fingerprint(item.id, item.sha256, digests[item.sha256], item.group))
        result, row = _evaluate_loaded(img, item, detector, perf)
        results.append(result)
        if row is not None:
            rows.append(row)
    if split == "heldout":
        tuning = _tuning_fingerprints(root, tuning_items, digests, budget)
        for pinned, other in others:
            tuning += _tuning_fingerprints(pinned, other.images, digests, budget)
        count, examples = count_leaks(heldout_prints, tuning)
        if count:
            raise ManifestError(
                f"held-out split leaks from tuning ({count} item(s)): " + "; ".join(examples)
            )
    return RunResult(
        split, tuple(results), tuple(rows), resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    )
