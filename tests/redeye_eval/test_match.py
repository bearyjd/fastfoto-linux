"""Matching rule, face accounting and change accounting on hand-built values."""

import numpy as np
import pytest

from fastfoto_linux.enhance.faces import Face
from fastfoto_linux.enhance.redeye import EyeFix
from fastfoto_linux.evaluation.redeye_manifest import GtEye, GtFace, Region
from fastfoto_linux.evaluation.redeye_match import (
    COLLATERAL_MARGIN,
    MATCH_IOD_FRACTION,
    count_changes,
    count_faces,
    fix_centroid,
    mask_iou,
    match_eyes,
)

IOD = 80.0
TOL = MATCH_IOD_FRACTION * IOD


def _face(face_id="a", x=100.0, y=100.0, red=(True, True), r=5.0) -> GtFace:
    return GtFace(face_id, (GtEye(x, y, r, red[0]), GtEye(x + IOD, y, r, red[1])))


def _fix(cx: float, cy: float, r: float = 5.0, landmark=None) -> EyeFix:
    x0, y0 = int(cx) - 12, int(cy) - 12
    rows, cols = np.ogrid[:25, :25]
    mask = (cols + x0 + 0.5 - cx) ** 2 + (rows + y0 + 0.5 - cy) ** 2 <= r * r
    mask.setflags(write=False)
    return EyeFix((x0, y0, x0 + 25, y0 + 25), mask, landmark or (cx, cy))


def test_the_match_constant_is_fifteen_percent() -> None:
    assert MATCH_IOD_FRACTION == 0.15
    assert TOL == 12.0


def test_centroid_uses_the_mask_with_pixel_centres_at_half() -> None:
    assert fix_centroid(_fix(100.0, 100.0)) == pytest.approx((100.0, 100.0), abs=1e-9)
    assert fix_centroid(_fix(100.5, 100.5, r=3.0)) == pytest.approx((100.5, 100.5), abs=0.1)


@pytest.mark.parametrize(
    ("offset", "matched"), [(0.14 * IOD, True), (TOL, True), (0.16 * IOD, False)]
)
def test_tolerance_is_inclusive_and_fifteen_percent(offset, matched) -> None:
    result = match_eyes([(100.0 + offset, 100.0)], [_face()])
    assert len(result.tp) == int(matched)
    assert len(result.fp_unmatched) == int(not matched)
    assert len(result.fn) == (1 if not matched else 0) + 1  # the other red eye is never found


def test_the_centroid_not_the_landmark_decides() -> None:
    near_mask_far_landmark = _fix(101.0, 100.0, landmark=(400.0, 400.0))
    result = match_eyes([fix_centroid(near_mask_far_landmark)], [_face()])
    assert [(m.face, m.eye) for m in result.tp] == [(0, 0)]


def test_a_match_to_a_non_red_eye_is_a_false_positive_of_its_own_kind() -> None:
    result = match_eyes([(100.0, 100.0)], [_face(red=(False, True))])
    assert result.tp == ()
    assert [(m.face, m.eye) for m in result.fp_non_red] == [(0, 0)]
    assert result.fp_unmatched == ()
    assert result.fn == ((0, 1),)


def test_an_unmatched_prediction_and_an_unmatched_red_eye() -> None:
    result = match_eyes([(10.0, 10.0)], [_face()])
    assert result.fp_unmatched == (0,)
    assert result.fn == ((0, 0), (0, 1))


def test_one_prediction_near_two_eyes_matches_once_with_a_deterministic_tie_break() -> None:
    near_both = [_face("b", x=104.0), _face("a", x=100.0)]
    result = match_eyes([(102.0, 100.0)], near_both)
    assert len(result.tp) == 1
    assert result.tp[0].face == 1  # face id "a" sorts first
    assert (1, 1) in result.fn or (1, 0) in result.fn or (0, 0) in result.fn
    assert (0, 0) in result.fn  # the other face's near eye gets no second match


def test_two_predictions_competing_for_one_eye_nearest_wins() -> None:
    result = match_eyes([(105.0, 100.0), (101.0, 100.0)], [_face()])
    assert [m.pred for m in result.tp] == [1]
    assert result.fp_unmatched == (0,)


def test_iou_is_one_for_the_same_disc_and_zero_for_disjoint() -> None:
    assert mask_iou(_fix(100.0, 100.0), GtEye(100.0, 100.0, 5.0, True)) == pytest.approx(1.0)
    assert mask_iou(_fix(100.0, 100.0), GtEye(200.0, 200.0, 5.0, True)) == 0.0
    half = mask_iou(_fix(100.0, 100.0), GtEye(104.0, 100.0, 5.0, True))
    assert 0.0 < half < 1.0


def _detected(face: GtFace, score=0.97, shift=0.0) -> Face:
    points = tuple((e.x + shift, e.y) for e in face.eyes)
    return Face(0, 0, 10, 10, (*points, (0, 0), (0, 0), (0, 0)), score)


def test_face_counts_found_skipped_missed_abstained() -> None:
    gt = [_face("a", y=100.0), _face("b", y=200.0), _face("c", y=300.0), _face("d", y=400.0)]
    detected = [
        _detected(gt[0]),
        _detected(gt[1], score=0.5),
        _detected(gt[2], score=0.97),
    ]
    eligible = [detected[0]]
    counts = count_faces(gt, detected, eligible, fn=[(0, 1), (3, 0)])
    assert (counts.found, counts.skipped_score, counts.skipped_small, counts.missed) == (1, 1, 1, 1)
    assert counts.abstained == 1  # only the found face's unmatched red eye


def test_face_matching_uses_the_same_tolerance() -> None:
    gt = [_face()]
    assert (
        count_faces(gt, [_detected(gt[0], shift=TOL)], [_detected(gt[0], shift=TOL)], []).found == 1
    )
    far = _detected(gt[0], shift=TOL + 1)
    assert count_faces(gt, [far], [far], []).found == 0


def _canvas() -> tuple[np.ndarray, np.ndarray]:
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    return img, img.copy()


def test_damage_counts_changes_inside_negative_boxes_per_category() -> None:
    img, out = _canvas()
    out[10:12, 10:12] = 5  # 4 pixels inside the lips box
    out[60, 60] = 5  # outside every box
    boxes = [Region("lips", (5, 5, 20, 20)), Region("signs", (50, 50, 55, 55))]
    counts = count_changes(img, out, [], [], boxes, negative_image=False)
    assert counts.damage == 4
    assert counts.damaged_categories == ("lips",)
    assert counts.changed == 5


def test_every_changed_pixel_in_a_negative_image_is_damage() -> None:
    img, out = _canvas()
    out[70, 70] = 9
    counts = count_changes(img, out, [], [], [], negative_image=True)
    assert counts.damage == 1
    assert counts.damaged_categories == ("other",)
    counts = count_changes(img, out, [], [], [Region("jewelry", (0, 0, 5, 5))], negative_image=True)
    assert counts.damage == 1 and counts.damaged_categories == ("jewelry",)


def test_a_positive_image_has_no_damage_without_boxes() -> None:
    img, out = _canvas()
    out[70, 70] = 9
    assert count_changes(img, out, [], [], [], negative_image=False).damage == 0


def test_locality_counts_changes_outside_the_fix_rois() -> None:
    img, out = _canvas()
    fix = EyeFix((10, 10, 30, 30), np.ones((20, 20), dtype=bool), (20.0, 20.0))
    out[15, 15] = 1  # inside the ROI
    assert count_changes(img, out, [fix], [], [], negative_image=False).locality == 0
    out[50, 50] = 1  # outside
    assert count_changes(img, out, [fix], [], [], negative_image=False).locality == 1


def test_collateral_is_informational_and_uses_the_dilated_gt_discs() -> None:
    assert COLLATERAL_MARGIN == 0.5
    img, out = _canvas()
    face = GtFace("a", (GtEye(30.0, 30.0, 4.0, True), GtEye(70.0, 30.0, 4.0, True)))
    out[30, 35] = 1  # 5.5 px from the first eye centre: inside r * 1.5 = 6
    out[30, 38] = 1  # 8.5 px: outside
    counts = count_changes(img, out, [], [face], [], negative_image=False)
    assert counts.collateral == 1
    assert counts.damage == 0
