"""Matching predictions to ground truth, and counting faces and changed pixels."""

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from fastfoto_linux.enhance.faces import Face
from fastfoto_linux.enhance.redeye import LANDMARKS_PER_FACE, MIN_FACE_SCORE, EyeFix
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
    ys, xs = np.nonzero(fix.mask)
    return fix.roi[0] + float(xs.mean()) + 0.5, fix.roi[1] + float(ys.mean()) + 0.5


def _interocular(face: GtFace) -> float:
    first, second = face.eyes
    return math.hypot(second.x - first.x, second.y - first.y)


def match_eyes(centroids: Sequence[tuple[float, float]], faces: Sequence[GtFace]) -> MatchResult:
    """Greedy one-to-one matching of predicted pupils to ground-truth eyes (nearest first)."""
    pairs: list[tuple[float, int, str, int, int]] = []
    for pred, (px, py) in enumerate(centroids):
        for f_index, face in enumerate(faces):
            tolerance = MATCH_IOD_FRACTION * _interocular(face)
            for e_index, eye in enumerate(face.eyes):
                distance = math.hypot(px - eye.x, py - eye.y)
                if distance <= tolerance:
                    pairs.append((distance, pred, face.id, e_index, f_index))
    pairs.sort()
    used_preds: set[int] = set()
    used_eyes: set[tuple[int, int]] = set()
    tp: list[EyeMatch] = []
    fp_non_red: list[EyeMatch] = []
    for distance, pred, _face_id, e_index, f_index in pairs:
        if pred in used_preds or (f_index, e_index) in used_eyes:
            continue
        used_preds.add(pred)
        used_eyes.add((f_index, e_index))
        match = EyeMatch(pred, f_index, e_index, distance)
        (tp if faces[f_index].eyes[e_index].red else fp_non_red).append(match)
    fn = tuple(
        (f_index, e_index)
        for f_index, face in enumerate(faces)
        for e_index, eye in enumerate(face.eyes)
        if eye.red and (f_index, e_index) not in used_eyes
    )
    unmatched = tuple(p for p in range(len(centroids)) if p not in used_preds)
    return MatchResult(tuple(tp), tuple(fp_non_red), unmatched, fn)


def _disc(shape: tuple[int, int], origin: tuple[int, int], eye: GtEye) -> np.ndarray:
    rows, cols = np.ogrid[: shape[0], : shape[1]]
    return (cols + origin[0] + 0.5 - eye.x) ** 2 + (rows + origin[1] + 0.5 - eye.y) ** 2 <= (
        eye.r**2
    )


def mask_iou(fix: EyeFix, eye: GtEye) -> float:
    """Intersection over union of the fix mask and the ground-truth disc, in image coordinates."""
    x0, y0, x1, y1 = fix.roi
    left = min(x0, math.floor(eye.x - eye.r))
    top = min(y0, math.floor(eye.y - eye.r))
    right = max(x1, math.ceil(eye.x + eye.r) + 1)
    bottom = max(y1, math.ceil(eye.y + eye.r) + 1)
    canvas = np.zeros((bottom - top, right - left), dtype=bool)
    canvas[y0 - top : y1 - top, x0 - left : x1 - left] = fix.mask
    disc = _disc(canvas.shape, (left, top), eye)
    union = int((canvas | disc).sum())
    return int((canvas & disc).sum()) / union if union else 0.0


def _near(face: Face, gt: GtFace) -> bool:
    tolerance = MATCH_IOD_FRACTION * _interocular(gt)
    return all(
        math.hypot(point[0] - eye.x, point[1] - eye.y) <= tolerance
        for point, eye in zip(face.landmarks[:LANDMARKS_PER_FACE], gt.eyes, strict=True)
    )


def count_faces(
    gt_faces: Sequence[GtFace],
    detected: Sequence[Face],
    eligible: Sequence[Face],
    fn: Sequence[tuple[int, int]],
) -> FaceCounts:
    """Found / skipped / missed ground-truth faces, and red eyes abstained in found faces."""
    found: set[int] = set()
    skipped_score = skipped_small = missed = 0
    for index, gt in enumerate(gt_faces):
        if any(_near(face, gt) for face in eligible):
            found.add(index)
            continue
        matching = [face for face in detected if _near(face, gt)]
        if not matching:
            missed += 1
        elif any(face.score >= MIN_FACE_SCORE for face in matching):
            skipped_small += 1
        else:
            skipped_score += 1
    abstained = sum(1 for face_index, _eye in fn if face_index in found)
    return FaceCounts(len(found), skipped_score, skipped_small, missed, abstained)


def _union_of_rois(shape: tuple[int, ...], fixes: Sequence[EyeFix]) -> np.ndarray:
    covered = np.zeros(shape[:2], dtype=bool)
    for fix in fixes:
        x0, y0, x1, y1 = fix.roi
        covered[y0:y1, x0:x1] = True
    return covered


def _union_of_regions(shape: tuple[int, ...], regions: Sequence[Region]) -> np.ndarray:
    covered = np.zeros(shape[:2], dtype=bool)
    for region in regions:
        x0, y0, x1, y1 = region.box
        covered[y0:y1, x0:x1] = True
    return covered


def _dilated_discs(shape: tuple[int, ...], faces: Sequence[GtFace]) -> np.ndarray:
    covered = np.zeros(shape[:2], dtype=bool)
    for face in faces:
        for eye in face.eyes:
            if not eye.red:
                continue
            reach = GtEye(eye.x, eye.y, eye.r * (1 + COLLATERAL_MARGIN), True)
            left, top = max(0, math.floor(eye.x - reach.r)), max(0, math.floor(eye.y - reach.r))
            right = min(shape[1], math.ceil(eye.x + reach.r) + 1)
            bottom = min(shape[0], math.ceil(eye.y + reach.r) + 1)
            if right > left and bottom > top:
                covered[top:bottom, left:right] |= _disc(
                    (bottom - top, right - left), (left, top), reach
                )
    return covered


def count_changes(  # noqa: PLR0913
    img: np.ndarray,
    out: np.ndarray,
    fixes: Sequence[EyeFix],
    faces: Sequence[GtFace],
    negatives: Sequence[Region],
    *,
    negative_image: bool,
) -> ChangeCounts:
    """Changed pixels: total, outside the fix ROIs, damaging, and outside the GT discs."""
    changed = np.any(out != img, axis=2)
    damaged: list[str] = []
    damage = 0
    if negative_image:
        damage = int(changed.sum())
        if damage:
            damaged = sorted({r.category for r in negatives} or {"other"})
    else:
        for category in sorted({r.category for r in negatives}):
            hit = changed & _union_of_regions(
                img.shape, [r for r in negatives if r.category == category]
            )
            if hit.any():
                damaged.append(category)
        damage = int((changed & _union_of_regions(img.shape, negatives)).sum())
    return ChangeCounts(
        changed=int(changed.sum()),
        locality=int((changed & ~_union_of_rois(img.shape, fixes)).sum()),
        damage=damage,
        collateral=int((changed & ~_dilated_discs(img.shape, faces)).sum()),
        damaged_categories=tuple(damaged),
    )
