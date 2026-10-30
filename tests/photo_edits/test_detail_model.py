"""PhotoDetail value rules, the schema 6 constants and the recipe field."""

import dataclasses
from pathlib import Path

import pytest

import fastfoto_linux.photo_edits as package
from fastfoto_linux.photo_edits import (
    PhotoDetail,
    PhotoEditError,
    PhotoEditRecipe,
    detail,
    model,
    results,
)
from tests.photo_edits.helpers import source_at

V6 = (6, "photo-detail-v1")
FIELDS = ["denoise_luma", "denoise_chroma", "sharpen"]


def test_defaults_and_limits_are_accepted() -> None:
    assert PhotoDetail() == PhotoDetail(0, 0, 0)
    assert (PhotoDetail().denoise_luma, PhotoDetail().denoise_chroma) == (0, 0)
    for value in (0, 1, 50, 100):
        assert PhotoDetail(value, value, value).sharpen == value


@pytest.mark.parametrize(
    "value", [-1, 101, True, False, 1.0, "5", None, float("nan"), float("inf"), 1e999]
)
@pytest.mark.parametrize("field", FIELDS)
def test_invalid_values_are_rejected(field: str, value: object) -> None:
    with pytest.raises(PhotoEditError, match="between 0 and 100"):
        PhotoDetail(**{field: value})  # type: ignore[arg-type]


def test_it_is_immutable() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        PhotoDetail().sharpen = 3  # type: ignore[misc]


@pytest.mark.parametrize(
    "version",
    [
        (2, "photo-tone-v1"),
        (3, "photo-geometry-v1"),
        (4, "photo-geometry-v2"),
        (5, "photo-color-v1"),
    ],
)
def test_older_schemas_cannot_hold_non_neutral_detail(tmp_path: Path, version: tuple) -> None:
    source = source_at(tmp_path)
    for value in (PhotoDetail(1, 0, 0), PhotoDetail(0, 1, 0), PhotoDetail(0, 0, 1)):
        with pytest.raises(PhotoEditError, match="cannot contain detail adjustments"):
            PhotoEditRecipe(source, (), *version, detail=value)
    assert PhotoEditRecipe(source, (), *version, detail=PhotoDetail())


def test_schema_6_holds_any_valid_detail_including_neutral(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    assert PhotoEditRecipe(source, (), *V6).detail == PhotoDetail()
    full = PhotoEditRecipe(source, (), *V6, detail=PhotoDetail(100, 100, 100))
    assert full.detail.denoise_chroma == 100


def test_the_recipe_field_is_keyword_only_and_typed(tmp_path: Path) -> None:
    field = next(f for f in dataclasses.fields(PhotoEditRecipe) if f.name == "detail")
    assert field.kw_only
    with pytest.raises(PhotoEditError, match="detail"):
        PhotoEditRecipe(source_at(tmp_path), (), *V6, detail=(1, 2, 3))  # type: ignore[arg-type]


def test_constants_version_table_and_exports() -> None:
    assert (model.DETAIL_SCHEMA_VERSION, model.DETAIL_ALGORITHM_VERSION) == V6
    assert model.RECIPE_VERSIONS[6] == "photo-detail-v1"
    assert model.DETAIL_CONTROL_LIMIT == 100
    assert (model.SCHEMA_VERSION, model.ALGORITHM_VERSION) == (2, "photo-tone-v1")
    for name in (
        "PhotoDetail",
        "update_detail",
        "DETAIL_SCHEMA_VERSION",
        "DETAIL_ALGORITHM_VERSION",
    ):
        assert name in package.__all__ and hasattr(package, name)
    assert package.DETAIL_ALGORITHM_VERSION == "photo-detail-v1"
    assert detail.DENOISE_HALO == 7 // 2 + 15 // 2


def test_moved_result_records_are_still_importable_from_both_places() -> None:
    assert model.PhotoPreview is results.PhotoPreview is package.PhotoPreview
    assert model.SavedPhotoEdit is results.SavedPhotoEdit is package.SavedPhotoEdit
