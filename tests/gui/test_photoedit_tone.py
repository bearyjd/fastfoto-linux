"""Tone drafts use the existing immutable editor lifecycle and worker queue."""

from dataclasses import FrozenInstanceError

import numpy as np
import pytest

from fastfoto_linux.gui.photoeditjobs import PhotoEditResult
from fastfoto_linux.gui.state import ActionBlockedError
from fastfoto_linux.photo_edits import PhotoEditRecipe, PhotoTone, SavedPhotoEdit
from tests.gui.photoedit_helpers import finish, opened, preview, setup


def complete_latest(page, out):
    request = page.worker.requests[-1]
    finish(
        page,
        PhotoEditResult(
            "preview",
            request.generation,
            request.recipe,
            preview(request.recipe, request.generation, out),
        ),
    )
    return request


def test_neutral_noop_does_not_dirty_queue_or_create_undo(out):
    page = opened(out)
    initial = page.side.recipe
    count, generation = len(page.worker.requests), page.side.generation
    for field, value in (("brightness", 0), ("contrast", 0), ("saturation", 0), ("strength", 100)):
        page.side.set_tone(field, value)
    page.side.reset_tone()
    assert page.side.recipe is initial
    assert page.side.recipe.tone == PhotoTone()
    assert page.side.recipe.schema_version == 2
    assert page.side.recipe.algorithm_version == "photo-tone-v1"
    assert not page.side.dirty and not page.side.can_undo
    assert len(page.worker.requests) == count
    assert page.side.generation == generation


def test_no_eye_candidates_still_allow_tone_and_one_gesture_undo(out):
    page = setup(out)
    page.side.open_photo(0)
    request = page.worker.requests[-1]
    initial = PhotoEditRecipe(page.source)
    finish(
        page,
        PhotoEditResult(
            "open", request.generation, initial, preview(initial, request.generation, out)
        ),
    )
    page.side.begin_gesture()
    page.side.set_tone("brightness", 10)
    page.side.set_tone("brightness", 35)
    page.side.end_gesture()
    assert page.side.recipe.tone.brightness == 35
    assert page.side.recipe.eyes == () and page.side.selected_id == ""
    assert page.side.dirty and page.side.can_undo
    page.side.undo()
    assert page.side.recipe is initial
    assert not page.side.can_undo


def test_reset_adjustments_preserves_accepted_eyes_and_is_one_undo(out):
    page = opened(out)
    page.side.set_accepted("left", True)
    accepted = page.side.recipe.eyes
    page.side.set_tone("saturation", -100)
    page.side.set_tone("strength", 0)
    adjusted = page.side.recipe
    pixels = page.source.pixels.copy()
    page.side.reset_tone()
    assert page.side.recipe.tone == PhotoTone()
    assert page.side.recipe.eyes is accepted
    assert page.side.recipe.eyes[0].accepted
    np.testing.assert_array_equal(page.source.pixels, pixels)
    page.side.undo()
    assert page.side.recipe is adjusted


def test_reopened_legacy_noop_keeps_identity_effective_change_upgrades_and_undo_restores(out):
    page = setup(out)
    legacy = PhotoEditRecipe(page.source, schema_version=1, algorithm_version="redeye-v1")
    page.side.open_saved(out / "saved.json")
    request = page.worker.requests[-1]
    finish(
        page,
        PhotoEditResult(
            "reopen", request.generation, legacy, preview(legacy, request.generation, out)
        ),
    )
    page.side.set_tone("brightness", 0)
    assert page.side.recipe is legacy and not page.side.dirty
    page.side.set_tone("brightness", 1)
    assert page.side.recipe.schema_version == 2
    assert page.side.recipe.algorithm_version == "photo-tone-v1"
    assert legacy.schema_version == 1 and legacy.tone == PhotoTone()
    page.side.undo()
    assert page.side.recipe is legacy


def test_page_reset_restores_opened_tone_while_adjustment_reset_restores_neutral(out):
    page = setup(out)
    saved = PhotoEditRecipe(page.source, tone=PhotoTone(brightness=12, strength=75))
    page.side.open_saved(out / "saved.json")
    request = page.worker.requests[-1]
    finish(
        page,
        PhotoEditResult(
            "reopen", request.generation, saved, preview(saved, request.generation, out)
        ),
    )
    page.side.reset_tone()
    assert page.side.recipe.tone == PhotoTone()
    assert page.side.recipe is not saved
    page.side.reset()
    assert page.side.recipe is saved
    page.side.undo()
    assert page.side.recipe.tone == PhotoTone()


def test_latest_preview_and_save_share_complete_immutable_tone_recipe(out):
    page = opened(out)
    original = page.side.recipe
    page.side.set_tone("contrast", 5)
    first = page.worker.requests[-1]
    page.side.set_tone("contrast", 50)
    page.side.set_tone("saturation", -30)
    latest = page.side.recipe
    assert first.recipe.tone.contrast == 5
    assert latest.tone == PhotoTone(contrast=50, saturation=-30)
    assert original.tone == PhotoTone()
    with pytest.raises(FrozenInstanceError):
        latest.tone.contrast = 0
    assert not page.side.can_save
    with pytest.raises(ActionBlockedError):
        page.side.save()
    complete_latest(page, out)
    assert page.worker.requests[-1].recipe is latest
    assert not page.side.can_save
    complete_latest(page, out)
    assert page.side.can_save
    page.side.save()
    saving = page.worker.requests[-1]
    assert saving.recipe is latest and saving.recipe.source is original.source
    saved = SavedPhotoEdit(out / "new.jpg", out / "new.json", latest)
    finish(page, PhotoEditResult("save", saving.generation, recipe=latest, saved=saved))
    assert not page.side.dirty
    assert page.side.saved_edit is saved


def test_failed_latest_tone_preview_blocks_save_and_close_discards_stale_paths(out):
    page = opened(out)
    page.side.set_tone("brightness", 10)
    request = page.worker.requests[-1]
    finish(page, PhotoEditResult("preview", request.generation, error="synthetic render failure"))
    assert page.side.error == "synthetic render failure"
    assert not page.side.can_save
    page.side.set_tone("brightness", 20)
    stale = page.worker.requests[-1]
    late = preview(stale.recipe, stale.generation, out / "editor-cache")
    assert not page.side.close()
    assert page.side.close(discard_confirmed=True)
    finish(page, PhotoEditResult("preview", stale.generation, stale.recipe, late))
    assert not page.side.active and page.side.recipe is None
    assert not late.after.exists() and not late.before.exists()
    with pytest.raises(ActionBlockedError):
        page.side.set_tone("brightness", 30)
    page.side.open_saved(out / "saved.json")
    reopening = page.worker.requests[-1]
    # A late preview cannot replace the newly opening recipe or clear its busy state.
    page.side.complete(PhotoEditResult("preview", stale.generation, stale.recipe, late))
    assert page.side.active and page.side.busy and page.side.recipe is None
    reopened = PhotoEditRecipe(page.source, tone=PhotoTone(contrast=-25))
    finish(
        page,
        PhotoEditResult(
            "reopen", reopening.generation, reopened, preview(reopened, reopening.generation, out)
        ),
    )
    assert page.side.recipe is reopened and not page.side.dirty


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("exposure", 1),
        ("brightness", True),
        ("contrast", 1.5),
        ("brightness", 51),
        ("contrast", -51),
        ("saturation", 101),
        ("strength", -1),
    ],
)
def test_invalid_controls_leave_draft_and_queue_untouched(out, field, value):
    page = opened(out)
    initial = page.side.recipe
    count = len(page.worker.requests)
    with pytest.raises(ValueError):
        page.side.set_tone(field, value)
    assert page.side.recipe is initial
    assert len(page.worker.requests) == count
    assert not page.side.dirty


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("brightness", -50),
        ("brightness", 50),
        ("contrast", -50),
        ("contrast", 50),
        ("saturation", -100),
        ("saturation", 100),
        ("strength", 0),
    ],
)
def test_valid_extremes_preserve_complete_tone_recipe(out, field, value):
    page = opened(out)
    original = page.side.recipe
    page.side.set_tone(field, value)
    assert getattr(page.side.recipe.tone, field) == value
    assert page.side.recipe.source is original.source
    assert page.side.recipe.eyes is original.eyes
    assert page.worker.requests[-1].recipe is page.side.recipe
    neutral = 100 if field == "strength" else 0
    page.side.set_tone(field, neutral)
    assert page.side.recipe.tone == PhotoTone()
    assert page.side.recipe.schema_version == 2
