"""Per-eye decisions and manual correction stay local and replay from source."""

from dataclasses import replace
from pathlib import Path
from threading import Event

import numpy as np
import pytest
from PIL import Image

from fastfoto_linux.enhance.faces import Face
from fastfoto_linux.enhance.redeye import EyeFix, apply_fixes
from fastfoto_linux.photo_edits import (
    PREVIEW_MAX_PX,
    PhotoEditCancelledError,
    PhotoEditError,
    PhotoEditRecipe,
    detect_eyes,
    make_preview,
    manual_eye,
    render,
)
from tests.photo_edits.helpers import HEIGHT, LEFT, RIGHT, WIDTH, eye, source_at


@pytest.mark.parametrize("edits", [(), (eye(accepted=False),), (eye(strength=0),)])
def test_no_accepted_effect_changes_no_pixels(tmp_path: Path, edits: tuple) -> None:
    source = source_at(tmp_path)
    result = render(source, PhotoEditRecipe(source, edits), cancel=Event())
    assert np.array_equal(result, source.pixels)
    assert result is not source.pixels


def test_accept_one_eye_reject_other_preserves_source_and_locality(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    before = source.pixels.copy()
    left = eye()
    recipe = PhotoEditRecipe(source, (left, eye("right", accepted=False, right=True)))
    result = render(source, recipe, cancel=Event())
    x0, y0, x1, y1 = left.roi
    outside = np.ones(before.shape[:2], dtype=bool)
    outside[y0:y1, x0:x1] = False
    assert np.array_equal(result[outside], before[outside])
    assert np.array_equal(source.pixels, before)
    assert result[LEFT[1], LEFT[0] + 2, 0] < before[LEFT[1], LEFT[0] + 2, 0]
    assert np.array_equal(result[RIGHT[1], RIGHT[0]], before[RIGHT[1], RIGHT[0]])
    assert np.array_equal(result[LEFT[1], LEFT[0]], before[LEFT[1], LEFT[0]])


def test_full_strength_reuses_existing_correction(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    edit = eye()
    expected = apply_fixes(source.pixels, (EyeFix(edit.roi, edit.mask, edit.center),))
    result = render(source, PhotoEditRecipe(source, (edit,)), cancel=Event())
    assert np.array_equal(result, expected)


def test_strength_reduces_effect_without_accumulating_edits(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    full = render(source, PhotoEditRecipe(source, (eye(),)), cancel=Event())
    half_recipe = PhotoEditRecipe(source, (eye(strength=50),))
    half = render(source, half_recipe, cancel=Event())
    assert (
        np.abs(half.astype(int) - source.pixels).sum()
        < np.abs(full.astype(int) - source.pixels).sum()
    )
    assert np.array_equal(half, render(source, half_recipe, cancel=Event()))


def test_manual_ellipse_works_without_a_face_and_is_clipped(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    edit = manual_eye(source, eye_id="manual-1", cx=1, cy=1, rx=5, ry=4, strength=60)
    assert edit.origin == "manual"
    assert edit.accepted and edit.strength == 60
    assert edit.roi[0] == edit.roi[1] == 0
    assert edit.mask.any() and not edit.mask.flags.writeable
    assert edit.roi[2] <= source.width and edit.roi[3] <= source.height


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1, 0])
def test_manual_ellipse_rejects_invalid_radius(tmp_path: Path, bad: float) -> None:
    source = source_at(tmp_path)
    with pytest.raises(PhotoEditError):
        manual_eye(source, eye_id="manual", cx=48, cy=48, rx=bad, ry=5)


def test_overlapping_accepted_regions_are_rejected(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    with pytest.raises(PhotoEditError, match="overlap"):
        render(source, PhotoEditRecipe(source, (eye(), eye("duplicate"))), cancel=Event())


def test_recipe_cannot_render_against_another_source(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    changed = replace(source, sha256="0" * 64)
    with pytest.raises(PhotoEditError, match=r"source|hash"):
        render(changed, PhotoEditRecipe(source, (eye(),)), cancel=Event())


def test_detection_suggestions_are_pending_and_do_not_mutate_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = source_at(tmp_path)
    faces = (Face(20, 10, 120, 80, (LEFT, RIGHT, (80, 60), (60, 70), (100, 70)), 0.99),)
    monkeypatch.setattr("fastfoto_linux.enhance.redeye.detect_faces_full_res", lambda *_: faces)
    suggestions = detect_eyes(source, cancel=Event())
    assert len(suggestions) == 2
    assert all(not edit.accepted and edit.origin == "detected" for edit in suggestions)
    assert len({edit.id for edit in suggestions}) == 2
    assert np.array_equal(
        render(source, PhotoEditRecipe(source, suggestions), cancel=Event()), source.pixels
    )


def test_preview_is_bounded_and_keeps_full_resolution_coordinate_space(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    preview = make_preview(
        source,
        PhotoEditRecipe(source, (eye(),)),
        cache_dir=tmp_path / "cache",
        generation=7,
        cancel=Event(),
        selected_id="left",
    )
    assert (preview.source_width, preview.source_height) == (WIDTH, HEIGHT)
    assert preview.generation == 7 and preview.source_sha256 == source.sha256
    for path in (preview.before, preview.after, preview.roi_before, preview.roi_after):
        assert path is not None and path.parent == tmp_path / "cache"
        with Image.open(path) as image:
            assert max(image.size) <= PREVIEW_MAX_PX
        assert path.stat().st_mode & 0o077 == 0


def test_cancelled_render_and_preview_publish_nothing(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    cancelled = Event()
    cancelled.set()
    recipe = PhotoEditRecipe(source, (eye(),))
    with pytest.raises(PhotoEditCancelledError):
        render(source, recipe, cancel=cancelled)
    with pytest.raises(PhotoEditCancelledError):
        make_preview(source, recipe, cache_dir=tmp_path / "cache", generation=1, cancel=cancelled)
    assert not (tmp_path / "cache").exists()
