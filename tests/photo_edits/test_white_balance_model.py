"""PhotoWhiteBalance value rules, the schema 5 constants and the recipe field."""

import dataclasses
from pathlib import Path

import pytest

import fastfoto_linux.photo_edits as package
from fastfoto_linux.photo_edits import PhotoEditError, PhotoEditRecipe, PhotoWhiteBalance
from fastfoto_linux.photo_edits import model
from tests.photo_edits.helpers import source_at

V5 = (5, "photo-color-v1")


def test_defaults_and_limits_are_accepted() -> None:
    assert PhotoWhiteBalance() == PhotoWhiteBalance(0, 0)
    assert PhotoWhiteBalance().temperature == 0
    for value in (-100, -1, 1, 100):
        assert PhotoWhiteBalance(value, value) == PhotoWhiteBalance(value, value)


@pytest.mark.parametrize(
    "value", [101, -101, True, False, 1.0, 2.5, "1", None, float("nan"), float("inf")]
)
@pytest.mark.parametrize("field", ["temperature", "tint"])
def test_invalid_values_are_rejected(field: str, value: object) -> None:
    with pytest.raises(PhotoEditError, match="between -100 and 100"):
        PhotoWhiteBalance(**{field: value})  # type: ignore[arg-type]


def test_it_is_immutable() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        PhotoWhiteBalance().tint = 3  # type: ignore[misc]


@pytest.mark.parametrize(
    "version", [(2, "photo-tone-v1"), (3, "photo-geometry-v1"), (4, "photo-geometry-v2")]
)
def test_older_schemas_cannot_hold_a_non_neutral_balance(tmp_path: Path, version: tuple) -> None:
    source = source_at(tmp_path)
    with pytest.raises(PhotoEditError, match="cannot contain white balance"):
        PhotoEditRecipe(source, (), *version, white_balance=PhotoWhiteBalance(1, 0))
    assert PhotoEditRecipe(source, (), *version, white_balance=PhotoWhiteBalance())


def test_schema_5_holds_any_valid_balance(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    neutral = PhotoEditRecipe(source, (), *V5)
    assert neutral.white_balance == PhotoWhiteBalance()
    warm = PhotoEditRecipe(source, (), *V5, white_balance=PhotoWhiteBalance(-100, 100))
    assert warm.white_balance.tint == 100


def test_the_balance_must_be_a_validated_object(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    for bad in ((1, 2), {"temperature": 1, "tint": 2}, None):
        with pytest.raises(PhotoEditError, match="white balance"):
            PhotoEditRecipe(source, (), *V5, white_balance=bad)  # type: ignore[arg-type]


def test_positional_arguments_keep_their_meaning(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    recipe = PhotoEditRecipe(source, (), 5, "photo-color-v1", 80)
    assert recipe.quality == 80 and recipe.white_balance == PhotoWhiteBalance()


def test_constants_version_table_and_exports() -> None:
    assert (model.WHITE_BALANCE_SCHEMA_VERSION, model.WHITE_BALANCE_ALGORITHM_VERSION) == V5
    assert model.RECIPE_VERSIONS[5] == "photo-color-v1"
    assert model.WB_CONTROL_LIMIT == 100
    assert (model.SCHEMA_VERSION, model.ALGORITHM_VERSION) == (2, "photo-tone-v1")
    for name in (
        "PhotoWhiteBalance",
        "update_white_balance",
        "WHITE_BALANCE_SCHEMA_VERSION",
        "WHITE_BALANCE_ALGORITHM_VERSION",
    ):
        assert name in package.__all__ and hasattr(package, name)
    assert package.WHITE_BALANCE_ALGORITHM_VERSION == "photo-color-v1"
