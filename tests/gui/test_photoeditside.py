"""Recoverable decisions and asynchronous lifecycle, using only synthetic sources."""

from dataclasses import replace

import numpy as np
import pytest

from fastfoto_linux.gui.photoeditjobs import PhotoEditResult
from fastfoto_linux.gui.photoeditside import eligibility
from fastfoto_linux.gui.photos import PhotoItem
from fastfoto_linux.photo_edits import PhotoEditRecipe, SavedPhotoEdit
from tests.gui.photoedit_helpers import finish, opened, preview, setup, source


def test_only_processed_retained_original_is_eligible(out):
    src = source(out)
    item = PhotoItem(out, 1, src.path, out / "synthetic_a.jpg", out / "synthetic_b.jpg")
    assert eligibility(item) == ""
    assert "original" in eligibility(replace(item, original=None)).lower()
    assert "process" in eligibility(replace(item, unprocessed_reason="no crop")).lower()
    src.path.unlink()
    assert "missing" in eligibility(item).lower()


def test_open_requests_original_never_enhanced_and_detected_eyes_start_rejected(out):
    p = opened(out)
    assert p.worker.requests[0].path == p.source.path
    assert p.side.active and not p.side.dirty
    assert all(not eye.accepted for eye in p.side.recipe.eyes)
    assert p.side.recipe.source is p.source
    assert not p.side.can_undo


def test_accept_reject_and_undo_preserve_source_and_other_eye(out):
    p = opened(out)
    initial = p.side.recipe
    p.side.set_accepted("left", True)
    assert p.side.recipe.eyes[0].accepted
    assert not p.side.recipe.eyes[1].accepted
    assert not initial.eyes[0].accepted
    assert p.side.recipe.source is initial.source
    assert p.side.dirty and p.side.can_undo
    p.side.undo()
    assert p.side.recipe is initial
    assert not p.side.dirty


def test_strength_gesture_is_one_undo_snapshot(out):
    p = opened(out)
    p.side.begin_gesture()
    for strength in (90, 60, 0):
        p.side.set_strength("left", strength)
    p.side.end_gesture()
    assert p.side.recipe.eyes[0].strength == 0
    p.side.undo()
    assert p.side.recipe.eyes[0].strength == 100
    assert not p.side.can_undo


def test_reset_keeps_source_and_resets_decisions(out):
    p = opened(out)
    initial = p.side.recipe
    p.side.set_accepted("left", True)
    p.side.reset()
    assert p.side.recipe is initial
    assert not p.side.dirty


def test_pending_preview_coalesces_to_latest_recipe_and_selection(out):
    p = opened(out)
    p.side.set_accepted("left", True)
    first = p.worker.requests[-1]
    p.side.set_strength("left", 70)
    p.side.set_strength("left", 40)
    p.side.select_eye("right")
    assert len(p.worker.requests) == 2
    stale = preview(first.recipe, first.generation, out)
    finish(p, PhotoEditResult("preview", first.generation, first.recipe, stale))
    newest = p.worker.requests[-1]
    assert len(p.worker.requests) == 3
    assert newest.recipe.eyes[0].strength == 40
    assert newest.selected_id == "right"
    assert p.side.preview is not stale
    current = preview(newest.recipe, newest.generation, out)
    finish(p, PhotoEditResult("preview", newest.generation, newest.recipe, current))
    assert p.side.preview is current


def test_close_requires_discard_confirmation_and_drops_late_callbacks(out):
    p = opened(out)
    p.side.set_accepted("left", True)
    request = p.worker.requests[-1]
    assert not p.side.close()
    assert p.side.active and p.side.dirty
    assert p.side.close(discard_confirmed=True)
    assert not p.side.active
    late = preview(request.recipe, request.generation, out)
    finish(p, PhotoEditResult("preview", request.generation, request.recipe, late))
    assert not p.side.active
    assert p.side.preview is None
    assert "cancel" in p.worker.names


def test_late_open_after_close_cannot_reactivate_editor(out):
    p = setup(out)
    p.side.open_photo(0)
    request = p.worker.requests[-1]
    assert p.side.close(discard_confirmed=True)
    finish(p, PhotoEditResult("open", request.generation, PhotoEditRecipe(p.source)))
    assert not p.side.active


def test_busy_worker_blocks_open_without_enqueuing(out):
    p = setup(out)
    p.worker.busy = True
    with pytest.raises(RuntimeError, match=r"busy|running|wait"):
        p.side.open_photo(0)
    assert not p.worker.requests


def test_save_dispatches_original_recipe_and_success_retains_saved_files(out):
    p = opened(out)
    p.side.set_accepted("left", True)
    request = p.worker.requests[-1]
    finish(p, PhotoEditResult("preview", request.generation, request.recipe))
    p.side.save()
    request = p.worker.requests[-1]
    assert request.operation == "save"
    assert request.recipe.source is p.source
    saved = SavedPhotoEdit(
        out / "synthetic_edit-0001.jpg", out / "synthetic_edit-0001.json", request.recipe
    )
    finish(p, PhotoEditResult("save", request.generation, request.recipe, saved=saved))
    assert p.side.saved_edit is saved
    assert not p.side.dirty
    assert p.source.path.exists()


def test_reopen_requests_json_and_errors_remain_visible(out):
    p = setup(out)
    sidecar = out / "synthetic_edit-0001.json"
    p.side.open_saved(sidecar)
    request = p.worker.requests[-1]
    assert request.operation == "reopen" and request.path == sidecar
    finish(p, PhotoEditResult("reopen", request.generation, error="source hash changed"))
    assert "source hash changed" in p.side.error
    assert not p.side.can_save


def test_manual_ellipse_uses_source_pixels_and_is_undoable(out):
    p = opened(out)
    calls = []
    base = p.side.recipe.eyes[0]

    def manual(src, **kwargs):
        calls.append((src, kwargs))
        return replace(base, id=kwargs["eye_id"], origin="manual", accepted=True)

    p.side._tools = replace(p.side._tools, manual=manual)
    p.side.add_ellipse(23, 23, 3, 3)
    assert calls[0][0] is p.source
    assert dict(cx=23, cy=23, rx=3, ry=3).items() <= calls[0][1].items()
    assert calls[0][1]["eye_id"] not in {"left", "right"}
    assert p.side.recipe.eyes[-1].origin == "manual"
    assert p.side.recipe.eyes[-1].accepted
    p.side.undo()
    assert len(p.side.recipe.eyes) == 2


def test_preview_and_discard_never_rewrite_source_jpeg(out):
    p = opened(out)
    original_bytes = p.source.path.read_bytes()
    p.side.set_accepted("left", True)
    p.side.undo()
    assert p.side.close(discard_confirmed=True)
    assert p.source.path.read_bytes() == original_bytes


def test_late_preview_from_closed_photo_cannot_replace_new_open(out):
    p = opened(out)
    p.side.set_accepted("left", True)
    old = p.worker.requests[-1]
    p.side.close(discard_confirmed=True)
    p.worker.busy = False
    p.side.open_photo(0)
    new = p.worker.requests[-1]
    finish(
        p,
        PhotoEditResult(
            "preview", old.generation, old.recipe, preview(old.recipe, old.generation, out)
        ),
    )
    assert p.side.recipe is None
    assert p.side.generation == new.generation
    recipe = PhotoEditRecipe(p.source)
    finish(p, PhotoEditResult("open", new.generation, recipe, preview(recipe, new.generation, out)))
    assert p.side.recipe is recipe


def test_numeric_replacement_uses_authoritative_backend_geometry_and_remove_undo(out):
    p = opened(out)
    original = p.side.recipe.eyes[0]
    adjusted = replace(
        original,
        roi=(10, 10, 18, 16),
        center=(14, 13),
        mask=np.ones((6, 8), bool),
        origin="manual",
        accepted=True,
    )
    calls = []

    def manual(src, **kwargs):
        calls.append((src, kwargs))
        return adjusted

    p.side._tools = replace(p.side._tools, manual=manual)
    p.side.replace_ellipse("left", 14, 13, 4, 3)
    assert calls[0][0] is p.source
    assert dict(eye_id="left", cx=14, cy=13, rx=4, ry=3).items() <= calls[0][1].items()
    assert p.side.recipe.eyes[0] is adjusted
    p.side.remove_eye("left")
    assert [eye.id for eye in p.side.recipe.eyes] == ["right"]
    p.side.undo()
    assert p.side.recipe.eyes[0] is adjusted


def test_editor_blocks_scans_and_mode_changes_until_closed(out):
    p = opened(out)
    p.controller._scanner_ready = True
    assert not p.controller.can_scan
    with pytest.raises(RuntimeError, match=r"review|edit|close"):
        p.controller.start_scan()
    with pytest.raises(RuntimeError, match=r"review|edit|close"):
        p.controller.set_mode("documents")
