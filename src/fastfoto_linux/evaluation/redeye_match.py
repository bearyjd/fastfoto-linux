"""Matching predictions to ground truth, and counting faces and changed pixels."""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from fastfoto_linux.enhance.faces import Face
from fastfoto_linux.enhance.redeye import EyeFix
from fastfoto_linux.evaluation.redeye_manifest import GtEye, GtFace, Region

MATCH_IOD_FRACTION = 0.15
COLLATERAL_MARGIN = 0.5


@dataclass(frozen=True)
class EyeMatch:
    pred: int
    face: int
    eye: int
    distance: float


@dataclass(frozen=True)
class MatchResult:
    tp: tuple[EyeMatch, ...]
    fp_non_red: tuple[EyeMatch, ...]
    fp_unmatched: tuple[int, ...]
    fn: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class FaceCounts:
    found: int
    skipped_score: int
    skipped_small: int
    missed: int
    abstained: int


@dataclass(frozen=True)
class ChangeCounts:
    changed: int
    locality: int
    damage: int
    collateral: int
    damaged_categories: tuple[str, ...]


def fix_centroid(fix: EyeFix) -> tuple[float, float]:
    """The mask centroid in image coordinates (pixel centres at +0.5), not the landmark."""
    raise NotImplementedError


def match_eyes(centroids: Sequence[tuple[float, float]], faces: Sequence[GtFace]) -> MatchResult:
    raise NotImplementedError


def mask_iou(fix: EyeFix, eye: GtEye) -> float:
    raise NotImplementedError


def count_faces(
    gt_faces: Sequence[GtFace],
    detected: Sequence[Face],
    eligible: Sequence[Face],
    fn: Sequence[tuple[int, int]],
) -> FaceCounts:
    raise NotImplementedError


def count_changes(
    img: np.ndarray,
    out: np.ndarray,
    fixes: Sequence[EyeFix],
    faces: Sequence[GtFace],
    negatives: Sequence[Region],
    *,
    negative_image: bool,
) -> ChangeCounts:
    raise NotImplementedError
