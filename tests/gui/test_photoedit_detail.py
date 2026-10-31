"""Denoise and sharpen drafts use the existing immutable editor lifecycle."""

import math

import pytest

from fastfoto_linux.photo_edits import PhotoDetail, PhotoEditError, PhotoTone, PhotoWhiteBalance
from tests.gui.photoedit_helpers import opened

BAD_FIELD = "Choose a noise reduction or sharpening adjustment."
FIELDS = ("denoise_luma", "denoise_chroma", "sharpen")


def test_each_field_sets_its_own_value_as_one_change_one_undo_and_upgrades(out):
    for index, field in enumerate(FIELDS):
        page = opened(out)
        initial = page.side.recipe
        page.side.set_detail(field, 30 + index)
        expected = {name: 0 for name in FIELDS} | {field: 30 + index}
        assert page.side.recipe.detail == PhotoDetail(**expected)
        assert page.side.recipe.schema_version == 6
        assert page.side.recipe.algorithm_version == "photo-detail-v1"
        assert page.side.dirty and len(page.side._undo) == 1
        page.side.undo()
        assert page.side.recipe is initial and not page.side.can_undo


def test_gesture_of_ten_values_is_one_undo_entry(out):
    page = opened(out)
    page.side.begin_gesture()
    for value in range(1, 11):
        page.side.set_detail("sharpen", value)
    page.side.end_gesture()
    assert page.side.recipe.detail.sharpen == 10
    assert len(page.side._undo) == 1


def test_same_value_adds_no_undo_entry_or_request(out):
    page = opened(out)
    initial, count = page.side.recipe, len(page.worker.requests)
    for field in FIELDS:
        page.side.set_detail(field, 0)
    assert page.side.recipe is initial and not page.side.can_undo and not page.side.dirty
    assert len(page.worker.requests) == count


def test_bad_field_and_out_of_range_values_are_rejected(out):
    page = opened(out)
    initial = page.side.recipe
    for bad_field in ("temperature", "", "brightness", "Sharpen"):
        with pytest.raises(ValueError, match=BAD_FIELD):
            page.side.set_detail(bad_field, 1)
    for bad in (101, -1, True, False, 1.0, 2.5, "1", None, math.nan, math.inf):
        with pytest.raises(PhotoEditError):
            page.side.set_detail("denoise_luma", bad)
    assert page.side.recipe is initial and not page.side.can_undo


def test_extremes_are_accepted(out):
    page = opened(out)
    for field in FIELDS:
        page.side.set_detail(field, 100)
    assert page.side.recipe.detail == PhotoDetail(100, 100, 100)
    page.side.set_detail("sharpen", 0)
    assert page.side.recipe.detail == PhotoDetail(100, 100, 0)


def test_reset_adjustments_neutralizes_detail_white_balance_and_tone_in_one_step(out):
    page = opened(out)
    page.side.set_accepted("left", True)
    page.side.set_tone("contrast", 20)
    page.side.set_white_balance("tint", 5)
    page.side.set_detail("denoise_luma", 40)
    page.side.set_detail("sharpen", 70)
    adjusted, depth = page.side.recipe, len(page.side._undo)
    accepted = adjusted.eyes
    page.side.reset_tone()
    recipe = page.side.recipe
    assert recipe.detail == PhotoDetail() and recipe.tone == PhotoTone()
    assert recipe.white_balance == PhotoWhiteBalance()
    assert recipe.eyes is accepted
    assert len(page.side._undo) == depth + 1
    page.side.undo()
    assert page.side.recipe is adjusted
    assert page.side.recipe.detail == PhotoDetail(40, 0, 70)


def test_reset_adjustments_with_only_detail_set_clears_it(out):
    page = opened(out)
    page.side.set_detail("denoise_chroma", 25)
    page.side.reset_tone()
    assert page.side.recipe.detail == PhotoDetail()
    assert len(page.side._undo) == 2
    assert page.side.recipe.schema_version == 6


def test_reset_adjustments_on_neutral_draft_is_still_a_no_op(out):
    page = opened(out)
    initial = page.side.recipe
    page.side.reset_tone()
    assert page.side.recipe is initial and not page.side.can_undo


def test_page_reset_restores_the_opened_recipe_including_detail(out):
    page = opened(out)
    page.side.set_detail("sharpen", 50)
    page.side.set_detail("denoise_luma", 10)
    page.side.reset()
    assert page.side.recipe is page.side._initial
    assert page.side.recipe.detail == PhotoDetail()


def test_presets_leave_detail_alone_and_matching_ignores_it(out):
    page = opened(out)
    page.side.set_detail("denoise_luma", 35)
    page.side.set_detail("sharpen", 60)
    page.side.apply_preset("warm")
    assert page.side.recipe.detail == PhotoDetail(35, 0, 60)
    assert page.side.recipe.white_balance == PhotoWhiteBalance(25, 0)
    assert page.side.active_preset == "warm"
    page.side.set_detail("denoise_chroma", 9)
    assert page.side.active_preset == "warm"
    page.side.apply_preset("mono")
    assert page.side.recipe.detail == PhotoDetail(35, 9, 60)
