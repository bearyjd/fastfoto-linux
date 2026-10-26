"""Run the auto red-eye path over a manifest and collect per-image results."""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from fastfoto_linux.enhance.faces import Face, FaceDetector
from fastfoto_linux.enhance.redeye import EyeFix
from fastfoto_linux.evaluation.redeye_manifest import Manifest, ManifestImage

EVAL_VERSION = 1


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
    """What the auto red-eye path finds in ``img``, and the faces behind it."""
    raise NotImplementedError


def evaluate_image(
    img: np.ndarray, item: ManifestImage, detector: FaceDetector | None
) -> ImageResult:
    raise NotImplementedError


def run_eval(
    manifest: Manifest,
    split: str,
    *,
    detector: FaceDetector | None = None,
    tuning_manifests: Sequence[Manifest] = (),
    perf: bool = True,
) -> RunResult:
    raise NotImplementedError
