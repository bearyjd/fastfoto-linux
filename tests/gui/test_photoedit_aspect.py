"""Crop shapes in the Qt-free photo editor: one lock, kept by shape actions, dropped by others."""

import json

import pytest

from fastfoto_linux.gui import photoeditaspectactions as aspect_actions
from fastfoto_linux.gui.photoeditaspect import fit_centred
from fastfoto_linux.gui.state import ActionBlockedError
from fastfoto_linux.photo_edits import frame_size, min_crop_size, output_size, recipe_bytes
from tests.gui.photoedit_helpers import opened, setup

TOO_SMALL = "This photo is too small for that crop shape at the 5 mm minimum."
BLOCKED = "Turn on Crop and rotate to change the framing."
FULL = (0, 0, 100, 60)


def editor(out, **kwargs):
    """A 100 x 60 photo at 100 dpi (20 px minimum crop), already in Crop and rotate."""
    page = opened(out, **{"dpi": 100, **kwargs})
    page.side.set_geometry_mode(True)
    return page.side


def crop(side):
    return side.recipe.geometry.crop


def test_the_lock_is_free_after_open_and_close(out):
    page = opened(out, dpi=100)
    side = page.side
    assert (side.crop_aspect, side.aspect_portrait, side.crop_ratio) == ("free", False, None)
    assert side.can_swap_aspect is False
    side.set_geometry_mode(True)
    side.set_crop_aspect("4:3")
    assert side.crop_aspect == "4:3"
    assert side.close(discard_confirmed=True)
    assert side.crop_aspect == "free" and side._aspect_geometry is None
    side.open_photo(0)
    assert side.crop_aspect == "free" and side.aspect_portrait is False


@pytest.mark.parametrize(
    "act",
    [
        lambda s: s.set_crop_aspect("4:3"),
        lambda s: s.swap_crop_aspect(),
        lambda s: s.set_aspect_crop(10, 10, 50, 40),
    ],
)
def test_every_action_is_refused_outside_the_mode_and_while_not_editable(out, act):
    side = opened(out, dpi=100).side
    before = (side.recipe, len(side._undo))
    with pytest.raises(ActionBlockedError, match=BLOCKED):
        act(side)
    assert (side.recipe, len(side._undo)) == before
    waiting = setup(out, dpi=100).side
    waiting.open_photo(0)
    with pytest.raises(ActionBlockedError, match="Wait for the photo"):
        act(waiting)


def test_choosing_a_shape_fits_the_largest_centred_box_as_one_undo(out):
    side = editor(out)
    side.set_crop_aspect("4:3")
    assert crop(side) == (10, 0, 90, 60) and len(side._undo) == 1
    assert (side.crop_aspect, side.crop_ratio, side.aspect_portrait) == ("4:3", (4, 3), False)
    assert side.can_swap_aspect is True
    assert output_size(side.recipe.source, side.recipe.geometry) == (80, 60)
    side.undo()
    assert crop(side) is None and side.crop_aspect == "free"


def test_choosing_the_live_shape_again_and_free_add_no_undo_entry(out):
    side = editor(out)
    side.set_crop_aspect("4:3")
    draft = side.recipe
    side.set_crop_aspect("4:3")
    assert side.recipe is draft and len(side._undo) == 1
    side.set_crop_aspect("free")
    assert side.recipe is draft and len(side._undo) == 1 and side.crop_aspect == "free"
    assert side.crop_ratio is None and side.can_swap_aspect is False


def test_original_on_an_uncropped_photo_changes_nothing_but_the_lock_is_live(out):
    side = editor(out)
    draft = side.recipe
    side.set_crop_aspect("original")
    assert side.recipe is draft and not side._undo
    assert (side.crop_aspect, side.crop_ratio, side.can_swap_aspect) == ("original", (5, 3), True)
    side.clear_crop()
    assert side.crop_aspect == "original"


def test_original_fits_the_current_crop_to_the_frame_shape(out):
    side = editor(out)
    side.set_crop(10, 0, 90, 60)
    side.set_crop_aspect("original")
    assert crop(side) == (10, 6, 90, 54)


def test_original_of_a_square_photo_cannot_be_swapped(out):
    side = editor(out, size=(80, 80))
    side.set_crop_aspect("original")
    assert (side.crop_ratio, side.can_swap_aspect) == ((1, 1), False)
    side.set_crop_aspect("1:1")
    assert side.can_swap_aspect is False
    with pytest.raises(ActionBlockedError):
        side.swap_crop_aspect()


def test_an_unknown_shape_is_refused_before_any_change(out):
    side = editor(out)
    side.set_crop_aspect("4:3")
    before = (side.recipe, len(side._undo))
    with pytest.raises(ValueError, match="unknown crop shape"):
        side.set_crop_aspect("2:1")
    assert (side.recipe, len(side._undo), side.crop_aspect) == (*before, "4:3")


def test_a_shape_that_cannot_fit_at_the_minimum_is_refused_and_changes_nothing(out):
    side = editor(out, dpi=300)
    side.set_crop_aspect("4:3")
    before = (side.recipe, len(side._undo), side._aspect_geometry)
    with pytest.raises(ActionBlockedError) as error:
        side.set_crop_aspect("16:9")
    assert str(error.value) == TOO_SMALL
    assert (side.recipe, len(side._undo), side._aspect_geometry) == before
    assert side.crop_aspect == "4:3"


@pytest.mark.parametrize(
    ("turns", "box", "want"),
    [
        (0, (30, 0, 60, 60), (True, (3, 4), (30, 10, 60, 50))),
        (1, (30, 0, 60, 60), (False, (3, 4), (30, 10, 60, 50))),
        (0, (10, 10, 50, 50), (False, (4, 3), (10, 15, 50, 45))),
        (0, (10, 0, 90, 60), (False, (4, 3), (10, 0, 90, 60))),
    ],
)
def test_the_default_orientation_follows_the_crop_in_the_output(out, turns, box, want):
    side = editor(out)
    for _ in range(turns):
        side.rotate(True)
    side.set_crop(*box)
    side.set_crop_aspect("4:3")
    assert (side.aspect_portrait, side.crop_ratio, crop(side)) == want


def test_a_quarter_turn_output_has_the_chosen_shape(out):
    side = editor(out)
    side.rotate(True)
    side.set_crop(30, 0, 60, 60)
    side.set_crop_aspect("4:3")
    width, height = output_size(side.recipe.source, side.recipe.geometry)
    assert (width, height) == (40, 30)


def test_swap_transposes_the_box_as_one_undo_and_swapping_back_restores_it(out):
    side = editor(out)
    side.set_crop(20, 10, 60, 40)
    side.set_crop_aspect("4:3")
    assert crop(side) == (20, 10, 60, 40) and len(side._undo) == 1
    side.swap_crop_aspect()
    assert crop(side) == (25, 5, 55, 45) and len(side._undo) == 2
    assert (side.crop_aspect, side.aspect_portrait, side.crop_ratio) == ("4:3", True, (3, 4))
    side.swap_crop_aspect()
    assert crop(side) == (20, 10, 60, 40) and side.aspect_portrait is False


def test_a_swap_that_cannot_fit_is_refused_and_keeps_the_orientation(out):
    side = editor(out, dpi=300)
    side.set_crop_aspect("4:3")
    before = (side.recipe, len(side._undo), side._aspect_geometry)
    with pytest.raises(ActionBlockedError) as error:
        side.swap_crop_aspect()
    assert str(error.value) == TOO_SMALL
    assert (side.recipe, len(side._undo), side._aspect_geometry) == before
    assert side.aspect_portrait is False


def test_swapping_a_free_crop_is_refused(out):
    side = editor(out)
    with pytest.raises(ActionBlockedError):
        side.swap_crop_aspect()
    assert not side._undo


def test_rotating_with_a_live_lock_keeps_the_crop_and_flips_the_orientation(out):
    side = editor(out)
    side.set_crop_aspect("4:3")
    box = crop(side)
    side.rotate(True)
    assert crop(side) == box and len(side._undo) == 2
    assert (side.crop_aspect, side.aspect_portrait, side.crop_ratio) == ("4:3", True, (4, 3))
    for _ in range(3):
        side.rotate(True)
    assert side.recipe.geometry.quarter_turns == 0 and crop(side) == box
    assert (side.crop_aspect, side.aspect_portrait, side.crop_ratio) == ("4:3", False, (4, 3))


def test_original_keeps_its_frame_ratio_through_every_turn(out):
    side = editor(out)
    side.set_crop_aspect("original")
    for _ in range(4):
        side.rotate(False)
        assert (side.crop_aspect, side.crop_ratio) == ("original", (5, 3))


LOCK_DROPS = {
    "set_crop": lambda s: s.set_crop(10, 0, 89, 60),
    "clear_crop": lambda s: s.clear_crop(),
    "reset_geometry": lambda s: s.reset_geometry(),
    "set_straighten": lambda s: s.set_straighten(20),
    "undo_to_another_geometry": lambda s: (s.rotate(True), s.undo()),
    "page_reset": lambda s: s.reset(),
}


@pytest.mark.parametrize("name", LOCK_DROPS)
def test_every_other_geometry_change_drops_the_lock_to_free(out, name):
    side = editor(out)
    side.set_crop_aspect("4:3")
    assert side.crop_aspect == "4:3"
    LOCK_DROPS[name](side)
    assert side.crop_aspect == "free" and side.crop_ratio is None


def test_undo_onto_the_geometry_the_lock_produced_shows_the_lock_again(out):
    side = editor(out)
    side.set_crop_aspect("4:3")
    side.set_crop(10, 0, 89, 60)
    assert side.crop_aspect == "free"
    side.undo()
    assert side.crop_aspect == "4:3" and crop(side) == (10, 0, 90, 60)


def test_a_rotate_after_an_edit_cannot_bring_a_stale_lock_back(out):
    side = editor(out)
    side.set_crop_aspect("4:3")
    side.set_crop(10, 0, 89, 60)
    side.rotate(True)
    assert side.crop_aspect == "free" and side.aspect_portrait is False
    side.rotate(False)
    assert side.crop_aspect == "free"


def test_a_ratio_drag_box_is_refitted_so_the_stored_box_matches_the_lock(out):
    side = editor(out)
    side.set_crop_aspect("4:3")
    side.set_aspect_crop(10, 10, 50, 40)
    assert crop(side) == (10, 10, 50, 40) and side.crop_aspect == "4:3"
    side.set_aspect_crop(10, 10, 60, 40)
    assert crop(side) == (15, 10, 55, 40) and side.crop_aspect == "4:3"


def test_a_ratio_drag_with_no_lock_is_a_plain_crop(out):
    side = editor(out)
    side.set_aspect_crop(10, 10, 60, 40)
    assert crop(side) == (10, 10, 60, 40) and side.crop_aspect == "free"


def test_a_drag_box_that_cannot_hold_the_shape_is_refused(out, monkeypatch):
    side = editor(out)
    side.set_crop_aspect("4:3")
    draft = side.recipe
    monkeypatch.setattr(aspect_actions, "fit_centred", lambda *args, **kwargs: None)
    with pytest.raises(ActionBlockedError) as error:
        side.set_aspect_crop(10, 10, 50, 40)
    assert str(error.value) == TOO_SMALL and side.recipe is draft


def test_an_angled_frame_uses_the_frame_of_that_angle(out):
    side = editor(out)
    side.set_straighten(100)
    frame = frame_size(side.recipe.source, side.recipe.geometry)
    assert frame != (100, 60)
    side.set_crop_aspect("3:2")
    minimum = min_crop_size(side.recipe.source, side.recipe.geometry)
    box = crop(side)
    assert fit_centred(box, (3, 2), frame=frame, minimum=minimum) == box
    assert box[0] >= 0 and box[2] <= frame[0] and box[1] >= 0 and box[3] <= frame[1]
    assert side.recipe.schema_version == 4


def test_the_recipe_holds_only_the_box_and_is_the_same_as_a_plain_crop(out):
    side = editor(out)
    side.set_crop_aspect("4:3")
    by_shape = recipe_bytes(side.recipe)
    side.clear_crop()
    side.set_crop(10, 0, 90, 60)
    assert recipe_bytes(side.recipe) == by_shape
    payload = json.loads(by_shape)
    assert payload["schema_version"] == 3
    assert set(payload["geometry"]) == {"crop", "quarter_turns"}
    assert "aspect" not in by_shape.decode() and "shape" not in by_shape.decode()


def test_an_uncropped_shape_and_a_turn_save_a_version_three_recipe_with_no_crop(out):
    side = editor(out)
    side.set_crop_aspect("original")
    side.rotate(True)
    assert side.recipe.schema_version == 3 and crop(side) is None
