"""White balance and preset drafts use the existing immutable editor lifecycle."""

import math

import pytest

from fastfoto_linux.gui.photoeditpresets import PRESETS, matching_preset, preset
from fastfoto_linux.photo_edits import (
    PhotoEditError,
    PhotoEditRecipe,
    PhotoTone,
    PhotoWhiteBalance,
)
from tests.gui.photoedit_helpers import opened, setup

TABLE = {
    "warm": ("Warm", 25, 0, 0, 0, 0, 100),
    "cool": ("Cool", -25, 0, 0, 0, 0, 100),
    "faded": ("Faded print", -10, -10, 0, 15, 25, 100),
    "mono": ("Black and white", 0, 0, 0, 10, -100, 100),
}
BAD_FIELD = "Choose a temperature or tint adjustment."


def test_exactly_four_presets_with_pinned_values():
    assert [p.id for p in PRESETS] == ["warm", "cool", "faded", "mono"]
    assert len({p.id for p in PRESETS}) == len(PRESETS)
    for item in PRESETS:
        label, temperature, tint, brightness, contrast, saturation, strength = TABLE[item.id]
        assert item.label == label and item.label.strip()
        assert item.white_balance == PhotoWhiteBalance(temperature, tint)
        assert item.tone == PhotoTone(brightness, contrast, saturation, strength)


def test_unknown_preset_id_is_a_user_message():
    assert preset("warm").label == "Warm"
    for bad in ("", "WARM", "sepia", "../etc"):
        with pytest.raises(ValueError, match=r"^Choose a listed preset\.$"):
            preset(bad)


def test_matching_preset_follows_values(out):
    page = opened(out)
    assert matching_preset(page.side.recipe) == ""
    page.side.apply_preset("cool")
    assert page.side.active_preset == "cool"
    assert matching_preset(page.side.recipe) == "cool"
    page.side.set_white_balance("tint", 1)
    assert page.side.active_preset == ""
    page.side.undo()
    assert page.side.active_preset == "cool"
    page.side.set_tone("brightness", 1)
    assert page.side.active_preset == ""


def test_matching_preset_is_empty_without_a_draft(out):
    assert setup(out).side.active_preset == ""


def test_set_white_balance_is_one_change_one_undo_and_upgrades(out):
    page = opened(out)
    initial = page.side.recipe
    page.side.set_white_balance("temperature", 30)
    assert page.side.recipe.white_balance == PhotoWhiteBalance(30, 0)
    assert page.side.recipe.schema_version == 5
    assert page.side.recipe.algorithm_version == "photo-color-v1"
    assert page.side.dirty and len(page.side._undo) == 1
    page.side.undo()
    assert page.side.recipe is initial and not page.side.can_undo


def test_gesture_of_ten_values_is_one_undo_entry(out):
    page = opened(out)
    page.side.begin_gesture()
    for value in range(1, 11):
        page.side.set_white_balance("tint", value)
    page.side.end_gesture()
    assert page.side.recipe.white_balance.tint == 10
    assert len(page.side._undo) == 1


def test_same_value_adds_no_undo_entry_or_request(out):
    page = opened(out)
    initial, count = page.side.recipe, len(page.worker.requests)
    page.side.set_white_balance("temperature", 0)
    page.side.set_white_balance("tint", 0)
    assert page.side.recipe is initial and not page.side.can_undo and not page.side.dirty
    assert len(page.worker.requests) == count


def test_bad_field_and_out_of_range_values_are_rejected(out):
    page = opened(out)
    initial = page.side.recipe
    with pytest.raises(ValueError, match=BAD_FIELD):
        page.side.set_white_balance("brightness", 1)
    with pytest.raises(ValueError, match=BAD_FIELD):
        page.side.set_white_balance("", 1)
    for bad in (101, -101, True, False, 1.0, 2.5, "1", None, math.nan, math.inf):
        with pytest.raises(PhotoEditError):
            page.side.set_white_balance("temperature", bad)
    assert page.side.recipe is initial and not page.side.can_undo


def test_extremes_are_accepted(out):
    page = opened(out)
    page.side.set_white_balance("temperature", 100)
    page.side.set_white_balance("tint", -100)
    assert page.side.recipe.white_balance == PhotoWhiteBalance(100, -100)


def test_apply_preset_is_one_undo_keeps_eyes_and_restores_the_exact_recipe(out):
    page = opened(out)
    page.side.set_accepted("left", True)
    before = page.side.recipe
    accepted = before.eyes
    page.side.apply_preset("warm")
    recipe = page.side.recipe
    assert recipe.white_balance == PhotoWhiteBalance(25, 0) and recipe.tone == PhotoTone()
    assert recipe.eyes is accepted and recipe.schema_version == 5
    assert page.side.active_preset == "warm"
    page.side.undo()
    assert page.side.recipe is before


def test_preset_sets_absolute_values_for_every_field_in_one_step(out):
    page = opened(out)
    page.side.set_tone("brightness", 40)
    page.side.set_white_balance("temperature", -60)
    before, undo_depth = page.side.recipe, len(page.side._undo)
    page.side.apply_preset("faded")
    assert page.side.recipe.tone == PhotoTone(0, 15, 25, 100)
    assert page.side.recipe.white_balance == PhotoWhiteBalance(-10, -10)
    assert len(page.side._undo) == undo_depth + 1
    page.side.undo()
    assert page.side.recipe is before


def test_reapplying_a_preset_is_a_no_op(out):
    page = opened(out)
    page.side.apply_preset("warm")
    applied, depth, count = page.side.recipe, len(page.side._undo), len(page.worker.requests)
    page.side.apply_preset("warm")
    assert page.side.recipe is applied and len(page.side._undo) == depth
    assert len(page.worker.requests) == count


def test_mono_on_a_v2_draft_stays_schema_2(out):
    page = opened(out)
    assert page.side.recipe.schema_version == 2
    page.side.apply_preset("mono")
    assert page.side.recipe.schema_version == 2
    assert page.side.recipe.algorithm_version == "photo-tone-v1"
    assert page.side.recipe.tone == PhotoTone(0, 10, -100, 100)
    assert page.side.recipe.white_balance == PhotoWhiteBalance()


def test_unknown_preset_changes_nothing(out):
    page = opened(out)
    initial = page.side.recipe
    with pytest.raises(ValueError, match=r"^Choose a listed preset\.$"):
        page.side.apply_preset("sepia")
    assert page.side.recipe is initial and not page.side.can_undo


def test_reset_adjustments_neutralizes_white_balance_and_tone_in_one_step(out):
    page = opened(out)
    page.side.set_accepted("left", True)
    page.side.apply_preset("faded")
    adjusted = page.side.recipe
    accepted = adjusted.eyes
    page.side.reset_tone()
    recipe = page.side.recipe
    assert recipe.tone == PhotoTone() and recipe.white_balance == PhotoWhiteBalance()
    assert recipe.eyes is accepted and recipe.schema_version == 5
    page.side.undo()
    assert page.side.recipe is adjusted


def test_reset_adjustments_with_only_white_balance_set(out):
    page = opened(out)
    page.side.set_white_balance("tint", 5)
    page.side.reset_tone()
    assert page.side.recipe.white_balance == PhotoWhiteBalance()
    assert len(page.side._undo) == 2


def test_reset_adjustments_on_neutral_draft_is_a_no_op(out):
    page = opened(out)
    initial = page.side.recipe
    page.side.reset_tone()
    assert page.side.recipe is initial and not page.side.can_undo


def test_page_reset_restores_the_opened_recipe_including_white_balance(out):
    page = opened(out)
    page.side.apply_preset("warm")
    page.side.set_white_balance("tint", 7)
    page.side.reset()
    assert page.side.recipe is page.side._initial
    assert page.side.recipe.white_balance == PhotoWhiteBalance()


def test_page_reset_keeps_an_opened_white_balance(out):
    page = opened(out)
    seeded = PhotoEditRecipe(
        page.source,
        page.side.recipe.eyes,
        schema_version=5,
        algorithm_version="photo-color-v1",
        white_balance=PhotoWhiteBalance(12, -3),
    )
    page.side._initial = page.side.recipe = seeded
    page.side.set_white_balance("temperature", 50)
    page.side.reset()
    assert page.side.recipe is seeded
    assert page.side.recipe.white_balance == PhotoWhiteBalance(12, -3)
