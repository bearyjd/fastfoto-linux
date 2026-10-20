"""Straighten is a geometry action of the Qt-free editor: one undo entry per gesture."""

from dataclasses import replace

import pytest
from PIL import Image

from fastfoto_linux.gui.photoeditjobs import PhotoEditResult
from fastfoto_linux.gui.state import ActionBlockedError
from fastfoto_linux.photo_edits import (
    PhotoEditError,
    PhotoEditRecipe,
    PhotoGeometry,
    frame_size,
)
from tests.gui.photoedit_helpers import eyes, finish, preview, setup, source


def opened_at(folder, *, dpi=100, dpi_y=None):
    """A 100 x 60 synthetic photo; 100 dpi keeps the 5 mm minimum small enough to straighten."""
    page = setup(folder)
    page.source = source(folder, dpi=dpi)
    if dpi_y is not None:
        page.source = replace(page.source, dpi_y=dpi_y, effective_dpi=dpi_y)
    page.side.open_photo(0)
    request = page.worker.requests[-1]
    recipe = PhotoEditRecipe(page.source, eyes())
    finish(
        page,
        PhotoEditResult(
            "open", request.generation, recipe, preview(recipe, request.generation, folder)
        ),
    )
    return page


def land(page, *, straightened):
    """Deliver the preview for the latest request, with a straightened file if asked."""
    request = page.worker.requests[-1]
    cache = page.side._cache_dir
    shown = preview(page.side.recipe, request.generation, cache)
    if straightened:
        path = cache / f"straightened-{request.generation}.png"
        Image.new("RGB", (96, 56), (90, 90, 90)).save(path)
        shown = replace(shown, straightened=path)
    finish(page, PhotoEditResult("preview", request.generation, page.side.recipe, shown))
    return shown


def test_straighten_is_refused_outside_the_mode_before_any_change(out):
    page = opened_at(out)
    with pytest.raises(ActionBlockedError):
        page.side.set_straighten(30)
    assert page.side.recipe.geometry == PhotoGeometry() and not page.side._undo


def test_an_equal_angle_is_a_no_op_with_no_undo_and_no_request(out):
    page = opened_at(out)
    side = page.side
    side.set_geometry_mode(True)
    requests = len(page.worker.requests)
    side.set_straighten(0)
    assert side.recipe.geometry == PhotoGeometry() and not side._undo
    assert len(page.worker.requests) == requests
    side.set_straighten(30)
    land(page, straightened=True)
    requests = len(page.worker.requests)
    side.set_straighten(30)
    assert len(side._undo) == 1 and len(page.worker.requests) == requests


def test_changing_the_angle_clears_the_crop_in_one_undo_entry(out):
    page = opened_at(out)
    side = page.side
    side.set_geometry_mode(True)
    side.set_straighten(20)
    fw, fh = frame_size(page.source, side.recipe.geometry)
    side.set_crop(5, 0, fw - 5, fh)
    cropped = side.recipe
    assert cropped.geometry.crop is not None
    undo_depth = len(side._undo)
    side.set_straighten(-10)
    assert side.recipe.geometry.straighten_tenths == -10 and side.recipe.geometry.crop is None
    assert len(side._undo) == undo_depth + 1
    side.undo()
    assert side.recipe is cropped
    assert side.recipe.geometry.straighten_tenths == 20 and side.recipe.geometry.crop is not None


def test_the_angle_keeps_the_quarter_turns(out):
    page = opened_at(out)
    side = page.side
    side.set_geometry_mode(True)
    side.rotate(True)
    side.set_straighten(15)
    assert side.recipe.geometry == PhotoGeometry(1, None, 15)


def test_a_drag_gesture_is_exactly_one_undo_entry(out):
    page = opened_at(out)
    side = page.side
    side.set_geometry_mode(True)
    initial = side.recipe
    side.begin_gesture()
    for tenths in (5, 10, 15, 20, 25):
        side.set_straighten(tenths)
    side.end_gesture()
    assert side.recipe.geometry.straighten_tenths == 25 and len(side._undo) == 1
    side.undo()
    assert side.recipe is initial


def test_reset_straighten_returns_to_zero_and_keeps_the_turns(out):
    page = opened_at(out)
    side = page.side
    side.set_geometry_mode(True)
    side.rotate(True)
    side.set_straighten(-40)
    side.reset_straighten()
    assert side.recipe.geometry == PhotoGeometry(1, None, 0)
    side.reset_straighten()
    assert len(side._undo) == 3


@pytest.mark.parametrize("tenths", [151, -151, 2.5, True])
def test_an_out_of_range_angle_is_rejected_and_the_draft_is_untouched(out, tenths):
    page = opened_at(out)
    side = page.side
    side.set_geometry_mode(True)
    before = side.recipe
    with pytest.raises(PhotoEditError):
        side.set_straighten(tenths)
    assert side.recipe is before and not side._undo


def test_non_square_pixels_disable_straighten_and_refuse_it(out):
    page = opened_at(out, dpi_y=200.0)
    side = page.side
    assert not side.can_straighten
    side.set_geometry_mode(True)
    before = side.recipe
    with pytest.raises(PhotoEditError, match="square pixels"):
        side.set_straighten(30)
    assert side.recipe is before and not side._undo


def test_square_pixels_allow_straighten_only_while_editable(out):
    page = opened_at(out)
    assert page.side.can_straighten
    page.side.close(discard_confirmed=True)
    assert not page.side.can_straighten


def test_eye_actions_stay_refused_with_an_angle(out):
    page = opened_at(out)
    side = page.side
    side.set_geometry_mode(True)
    side.set_straighten(30)
    with pytest.raises(ActionBlockedError):
        side.set_accepted("left", True)


def test_preview_current_tracks_the_latest_request(out):
    page = opened_at(out)
    side = page.side
    assert side.preview_current
    side.set_geometry_mode(True)
    side.set_straighten(30)
    assert not side.preview_current
    land(page, straightened=True)
    assert side.preview_current


def test_stale_straightened_files_are_discarded_when_a_new_preview_lands(out):
    page = opened_at(out)
    side = page.side
    side.set_geometry_mode(True)
    side.set_straighten(30)
    first = land(page, straightened=True)
    assert first.straightened.exists()
    side.set_straighten(0)
    land(page, straightened=False)
    assert not first.straightened.exists()


def test_setting_the_same_angle_keeps_the_crop(out):
    page = opened_at(out)
    side = page.side
    side.set_geometry_mode(True)
    side.set_straighten(20)
    fw, fh = frame_size(page.source, side.recipe.geometry)
    side.set_crop(5, 0, fw - 5, fh)
    cropped = side.recipe
    side.set_straighten(20)
    assert side.recipe is cropped
