"""Versioned immutable tone controls retain the legacy recipe calling convention."""

from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from fastfoto_linux.photo_edits import (
    PhotoEditError,
    PhotoEditRecipe,
    PhotoTone,
    update_tone,
)
from tests.photo_edits.helpers import eye, source_at


@pytest.mark.parametrize(
    "field,low,high",
    [
        ("brightness", -50, 50),
        ("contrast", -50, 50),
        ("saturation", -100, 100),
        ("strength", 0, 100),
    ],
)
def test_tone_accepts_exact_integer_endpoints(field: str, low: int, high: int) -> None:
    for value in (low, high):
        assert getattr(PhotoTone(**{field: value}), field) == value


@pytest.mark.parametrize(
    "field,bad",
    [
        ("brightness", -51),
        ("brightness", 51),
        ("contrast", -51),
        ("contrast", 51),
        ("saturation", -101),
        ("saturation", 101),
        ("strength", -1),
        ("strength", 101),
        ("brightness", True),
        ("contrast", False),
        ("saturation", 0.0),
        ("strength", "50"),
        ("brightness", float("nan")),
        ("contrast", float("inf")),
        ("saturation", None),
    ],
)
def test_tone_rejects_out_of_range_or_noninteger_controls(field: str, bad: object) -> None:
    with pytest.raises(PhotoEditError):
        PhotoTone(**{field: bad})


def test_tone_is_immutable_and_new_drafts_are_v2(tmp_path: Path) -> None:
    tone = PhotoTone()
    assert (tone.brightness, tone.contrast, tone.saturation, tone.strength) == (0, 0, 0, 100)
    with pytest.raises(FrozenInstanceError):
        tone.brightness = 1
    recipe = PhotoEditRecipe(source_at(tmp_path))
    assert (recipe.schema_version, recipe.algorithm_version) == (2, "photo-tone-v1")
    assert recipe.tone == tone


def test_legacy_positional_fields_and_keyword_only_tone(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    recipe = PhotoEditRecipe(source, (eye(),), 1, "redeye-v1", 87)
    assert recipe.quality == 87 and recipe.tone == PhotoTone()
    assert (recipe.schema_version, recipe.algorithm_version) == (1, "redeye-v1")
    with pytest.raises(TypeError):
        PhotoEditRecipe(source, (), 1, "redeye-v1", 87, PhotoTone())


def test_same_tone_returns_original_recipe_even_for_v1(tmp_path: Path) -> None:
    legacy = PhotoEditRecipe(source_at(tmp_path), (), 1, "redeye-v1")
    assert update_tone(legacy, PhotoTone()) is legacy
    modern = PhotoEditRecipe(legacy.source)
    assert update_tone(modern, PhotoTone()) is modern


def test_first_effective_tone_change_upgrades_only_new_snapshot(tmp_path: Path) -> None:
    legacy = PhotoEditRecipe(source_at(tmp_path), (eye(),), 1, "redeye-v1", 87)
    tone = PhotoTone(brightness=15, contrast=-25, saturation=80, strength=65)
    changed = update_tone(legacy, tone)
    assert changed is not legacy and changed.source is legacy.source
    assert changed.eyes is legacy.eyes and changed.quality == legacy.quality
    assert changed.tone == tone
    assert (changed.schema_version, changed.algorithm_version) == (2, "photo-tone-v1")
    assert (legacy.schema_version, legacy.algorithm_version, legacy.tone) == (
        1,
        "redeye-v1",
        PhotoTone(),
    )
    neutral = update_tone(changed, PhotoTone())
    assert (neutral.schema_version, neutral.algorithm_version) == (2, "photo-tone-v1")
    assert update_tone(changed, replace(tone)) is changed


@pytest.mark.parametrize("tone", [None, {}, 1, True])
def test_update_requires_validated_tone(tmp_path: Path, tone: object) -> None:
    with pytest.raises(PhotoEditError):
        update_tone(PhotoEditRecipe(source_at(tmp_path)), tone)


@pytest.mark.parametrize(
    "schema,algorithm", [(1, "photo-tone-v1"), (2, "redeye-v1"), (3, "photo-tone-v1")]
)
def test_recipe_rejects_unsupported_version_pairs(
    tmp_path: Path, schema: int, algorithm: str
) -> None:
    with pytest.raises(PhotoEditError):
        PhotoEditRecipe(source_at(tmp_path), schema_version=schema, algorithm_version=algorithm)


def test_v1_cannot_hold_nonneutral_tone(tmp_path: Path) -> None:
    with pytest.raises(PhotoEditError):
        PhotoEditRecipe(source_at(tmp_path), (), 1, "redeye-v1", tone=PhotoTone(brightness=1))


@pytest.mark.parametrize("tone", [None, {}, True])
def test_recipe_rejects_unvalidated_tone(tmp_path: Path, tone: object) -> None:
    with pytest.raises(PhotoEditError):
        PhotoEditRecipe(source_at(tmp_path), tone=tone)
