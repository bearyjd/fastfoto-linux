"""Geometry mode and actions use the existing immutable editor lifecycle and worker queue."""

from dataclasses import replace

import pytest

from fastfoto_linux.gui.photoeditjobs import PhotoEditResult
from fastfoto_linux.gui.state import ActionBlockedError
from fastfoto_linux.photo_edits import PhotoEditError, PhotoEditRecipe, PhotoGeometry
from tests.gui.photoedit_helpers import eyes, finish, opened, preview, setup

CROP = (10, 0, 90, 60)
BLOCKED = "Leave Crop and rotate to edit eyes."


def open_recipe(page, recipe, operation="reopen"):
    page.side.open_saved(page.source.path.parent / "saved.json")
    request = page.worker.requests[-1]
    finish(
        page,
        PhotoEditResult(
            operation,
            request.generation,
            recipe,
            preview(recipe, request.generation, page.source.path.parent),
        ),
    )


def eye_actions(side):
    return {
        "select_eye": lambda: side.select_eye("right"),
        "set_accepted": lambda: side.set_accepted("left", True),
        "set_strength": lambda: side.set_strength("left", 40),
        "add_ellipse": lambda: side.add_ellipse(30.0, 30.0, 5.0, 5.0),
        "replace_ellipse": lambda: side.replace_ellipse("left", 30.0, 30.0, 5.0, 5.0),
        "remove_eye": lambda: side.remove_eye("left"),
    }


def snapshot(page):
    side = page.side
    return (
        side.recipe,
        side.selected_id,
        len(side._undo),
        side.dirty,
        len(page.worker.requests),
        side.generation,
        side._manual_number,
        side.error,
    )


def test_mode_is_off_after_open_toggle_is_free_and_close_clears_it(out):
    page = opened(out)
    side = page.side
    assert side.geometry_mode is False
    before = snapshot(page)
    side.set_geometry_mode(True)
    assert side.geometry_mode is True
    assert snapshot(page) == before
    side.set_geometry_mode(False)
    side.set_geometry_mode(True)
    assert snapshot(page) == before
    assert side.close(discard_confirmed=True)
    assert side.geometry_mode is False


def test_leaving_the_mode_ends_an_open_gesture_so_later_edits_do_not_coalesce(out):
    page = opened(out)
    side = page.side
    side.set_geometry_mode(True)
    side.begin_gesture()
    side.rotate(True)
    side.set_geometry_mode(False)
    side.set_geometry_mode(True)
    side.rotate(True)
    assert len(side._undo) == 2


def test_reopening_clears_the_mode(out):
    page = opened(out)
    page.side.set_geometry_mode(True)
    assert page.side.close(discard_confirmed=True)
    page.side.open_photo(0)
    assert page.side.geometry_mode is False


def test_mode_requires_an_editable_draft(out):
    page = setup(out)
    page.side.open_photo(0)
    with pytest.raises(ActionBlockedError):
        page.side.set_geometry_mode(True)
    assert page.side.geometry_mode is False


@pytest.mark.parametrize(
    "name",
    ["select_eye", "set_accepted", "set_strength", "add_ellipse", "replace_ellipse", "remove_eye"],
)
def test_every_eye_action_is_refused_in_geometry_mode_before_any_change(out, name):
    page = opened(out)
    page.side.set_geometry_mode(True)
    before = snapshot(page)
    with pytest.raises(ActionBlockedError, match=BLOCKED):
        eye_actions(page.side)[name]()
    assert snapshot(page) == before
    page.side.set_geometry_mode(False)
    eye_actions(page.side)[name]()
    assert snapshot(page) != before or name == "select_eye"


def test_geometry_actions_are_refused_outside_the_mode(out):
    page = opened(out)
    before = snapshot(page)
    for action in (
        lambda: page.side.rotate(True),
        lambda: page.side.set_crop(*CROP),
        page.side.clear_crop,
        page.side.reset_geometry,
    ):
        with pytest.raises(ActionBlockedError):
            action()
    assert snapshot(page) == before


def test_tone_undo_and_reset_work_in_geometry_mode(out):
    page = opened(out)
    page.side.set_geometry_mode(True)
    initial = page.side.recipe
    page.side.set_tone("brightness", 10)
    assert page.side.recipe.tone.brightness == 10
    page.side.undo()
    assert page.side.recipe is initial
    page.side.rotate(True)
    page.side.reset()
    assert page.side.recipe is initial


def test_rotate_directions_wrap_and_each_is_one_undo(out):
    page = opened(out)
    side = page.side
    side.set_geometry_mode(True)
    initial = side.recipe
    side.rotate(True)
    assert side.recipe.geometry == PhotoGeometry(1)
    assert side.recipe.schema_version == 3
    assert side.recipe.algorithm_version == "photo-geometry-v1"
    side.rotate(False)
    side.rotate(False)
    assert side.recipe.geometry.quarter_turns == 3
    assert len(side._undo) == 3
    side.undo()
    assert side.recipe.geometry.quarter_turns == 0
    side.undo()
    side.undo()
    assert side.recipe is initial and not side._undo


def test_four_rotations_end_neutral_but_v3_with_four_undo_entries(out):
    page = opened(out)
    page.side.set_geometry_mode(True)
    for _ in range(4):
        page.side.rotate(True)
    recipe = page.side.recipe
    assert recipe.geometry == PhotoGeometry()
    assert recipe.schema_version == 3
    assert len(page.side._undo) == 4 and page.side.dirty


def test_rotation_keeps_the_crop_in_source_space(out):
    page = opened(out)
    side = page.side
    side.set_geometry_mode(True)
    side.set_crop(*CROP)
    side.rotate(True)
    assert side.recipe.geometry == PhotoGeometry(1, CROP)


def test_set_crop_is_one_undo_and_clear_crop_restores_full_frame(out):
    page = opened(out)
    side = page.side
    side.set_geometry_mode(True)
    side.set_crop(*CROP)
    assert side.recipe.geometry.crop == CROP and len(side._undo) == 1
    side.set_crop(*CROP)
    assert len(side._undo) == 1
    side.clear_crop()
    assert side.recipe.geometry.crop is None and len(side._undo) == 2


def test_full_frame_crop_and_noops_add_no_undo_dirty_or_preview(out):
    page = opened(out)
    side = page.side
    side.set_geometry_mode(True)
    initial, count, generation = side.recipe, len(page.worker.requests), side.generation
    side.set_crop(0, 0, 100, 60)
    side.clear_crop()
    side.reset_geometry()
    assert side.recipe is initial
    assert not side.dirty and not side.can_undo
    assert len(page.worker.requests) == count and side.generation == generation


def test_full_frame_crop_clears_an_existing_crop(out):
    page = opened(out)
    page.side.set_geometry_mode(True)
    page.side.set_crop(*CROP)
    page.side.set_crop(0, 0, 100, 60)
    assert page.side.recipe.geometry.crop is None


@pytest.mark.parametrize(
    "crop", [(10, 10, 12, 50), (50, 0, 20, 60), (0, 0, 101, 60), (-1, 0, 80, 60), (0.5, 0, 80, 60)]
)
def test_invalid_crop_raises_and_leaves_draft_untouched(out, crop):
    page = opened(out)
    page.side.set_geometry_mode(True)
    before = snapshot(page)
    with pytest.raises((PhotoEditError, ValueError, TypeError)):
        page.side.set_crop(*crop)
    assert snapshot(page) == before


def test_reset_geometry_is_one_undo_and_keeps_eyes_and_tone(out):
    page = opened(out)
    side = page.side
    side.set_accepted("left", True)
    side.set_tone("contrast", 20)
    side.set_geometry_mode(True)
    side.rotate(True)
    side.set_crop(*CROP)
    adjusted, depth = side.recipe, len(side._undo)
    side.reset_geometry()
    assert side.recipe.geometry == PhotoGeometry()
    assert side.recipe.tone.contrast == 20
    assert side.recipe.eyes[0].accepted and side.recipe.eyes == adjusted.eyes
    assert len(side._undo) == depth + 1
    side.undo()
    assert side.recipe is adjusted


def test_page_reset_restores_the_opened_v3_geometry_and_undo_returns(out):
    page = setup(out)
    saved = PhotoEditRecipe(
        page.source,
        eyes(),
        geometry=PhotoGeometry(2, CROP),
        schema_version=3,
        algorithm_version="photo-geometry-v1",
    )
    open_recipe(page, saved)
    side = page.side
    side.set_geometry_mode(True)
    side.reset_geometry()
    assert side.recipe.geometry == PhotoGeometry()
    side.rotate(True)
    side.reset()
    assert side.recipe is saved and side.recipe.geometry == PhotoGeometry(2, CROP)
    side.undo()
    assert side.recipe.geometry == PhotoGeometry(1)


def test_latest_preview_and_save_recipes_carry_geometry(out):
    page = opened(out)
    side = page.side
    side.set_geometry_mode(True)
    side.rotate(True)
    side.set_crop(*CROP)
    latest = side.recipe
    assert page.worker.requests[-1].operation == "preview"
    assert side._pending is not None and side._pending.recipe is latest
    for _ in range(2):
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
    assert side.can_save
    side.save()
    saving = page.worker.requests[-1]
    assert saving.operation == "save" and saving.recipe is latest
    assert saving.recipe.geometry == PhotoGeometry(1, CROP)


def test_stale_working_paths_are_discarded(out):
    page = opened(out)
    side = page.side
    cache = out / "editor-cache"
    first = preview(side.recipe, 90, cache)
    working = cache / "working-90.png"
    working.write_bytes(first.after.read_bytes())
    first = replace(first, working=working)
    side.preview = first
    second = replace(preview(side.recipe, 91, cache), working=cache / "working-91.png")
    (cache / "working-91.png").write_bytes(working.read_bytes())
    side._discard_preview(first, keeping=second)
    assert not working.exists() and not first.before.exists()
    assert second.working.exists()
    side._discard_preview(second)
    assert not second.working.exists()
