"""PhotoGeometry value rules, source-relative bounds and the version table."""

import dataclasses
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from fastfoto_linux.photo_edits import (
    GEOMETRY_ALGORITHM_VERSION,
    GEOMETRY_SCHEMA_VERSION,
    MIN_CROP_MM,
    PhotoEditError,
    PhotoEditRecipe,
    PhotoGeometry,
    min_crop_size,
)
from fastfoto_linux.photo_edits import model as model_module
from tests.photo_edits.helpers import HEIGHT, WIDTH, source_at
from tests.photo_edits.tone_helpers import tone_source


def _recipe(source: object, geometry: PhotoGeometry, schema: int = 3) -> PhotoEditRecipe:
    algorithm = model_module.RECIPE_VERSIONS[schema]
    return PhotoEditRecipe(
        source, schema_version=schema, algorithm_version=algorithm, geometry=geometry
    )


def test_constants_and_version_table() -> None:
    assert (GEOMETRY_SCHEMA_VERSION, GEOMETRY_ALGORITHM_VERSION) == (3, "photo-geometry-v1")
    assert MIN_CROP_MM == 5.0
    assert (model_module.TONE_SCHEMA_VERSION, model_module.TONE_ALGORITHM_VERSION) == (
        2,
        "photo-tone-v1",
    )
    assert model_module.RECIPE_VERSIONS == {
        1: "redeye-v1",
        2: "photo-tone-v1",
        3: "photo-geometry-v1",
        4: "photo-geometry-v2",
        5: "photo-color-v1",
    }
    # New drafts stay on the tone schema.
    assert (model_module.SCHEMA_VERSION, model_module.ALGORITHM_VERSION) == (2, "photo-tone-v1")


@pytest.mark.parametrize(
    ("schema", "algorithm"),
    [
        (3, "photo-tone-v1"),
        (2, "photo-geometry-v1"),
        (1, "photo-tone-v1"),
        (4, "photo-geometry-v1"),
        (5, "photo-geometry-v2"),
        (4, "photo-color-v1"),
        (0, "redeye-v1"),
        (True, "redeye-v1"),
        (3.0, "photo-geometry-v1"),
        (3, None),
        (3, b"photo-geometry-v1"),
    ],
)
def test_validate_version_is_an_exact_table_lookup(schema: object, algorithm: object) -> None:
    with pytest.raises(PhotoEditError):
        model_module.validate_version(schema, algorithm)


def test_validate_version_accepts_every_table_entry() -> None:
    for schema, algorithm in model_module.RECIPE_VERSIONS.items():
        model_module.validate_version(schema, algorithm)


def test_defaults_are_neutral_and_immutable() -> None:
    geometry = PhotoGeometry()
    assert (geometry.quarter_turns, geometry.crop) == (0, None)
    assert geometry == PhotoGeometry(0, None)
    with pytest.raises(dataclasses.FrozenInstanceError):
        geometry.quarter_turns = 1  # type: ignore[misc]


def test_recipe_defaults_to_neutral_keyword_only_geometry(tmp_path: Path) -> None:
    recipe = PhotoEditRecipe(source_at(tmp_path))
    assert recipe.geometry == PhotoGeometry()
    assert (recipe.schema_version, recipe.algorithm_version) == (2, "photo-tone-v1")
    field = next(f for f in dataclasses.fields(PhotoEditRecipe) if f.name == "geometry")
    assert field.kw_only
    with pytest.raises(PhotoEditError):
        PhotoEditRecipe(source_at(tmp_path), geometry=(1, None))  # type: ignore[arg-type]


@pytest.mark.parametrize("turns", [0, 1, 2, 3])
def test_valid_quarter_turns(turns: int) -> None:
    assert PhotoGeometry(turns).quarter_turns == turns


@pytest.mark.parametrize("turns", [True, False, 3.0, 4, -1, "1", None])
def test_invalid_quarter_turns_are_rejected(turns: object) -> None:
    with pytest.raises(PhotoEditError):
        PhotoGeometry(turns)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "crop",
    [
        [0, 0, 60, 60],
        (0, 0, 60),
        (0, 0, 60, 60, 1),
        (),
        (0, 0, 60.0, 60),
        (0, 0, True, 60),
        (0, 0, "60", 60),
        (-1, 0, 60, 60),
        (0, -1, 60, 60),
        (60, 0, 60, 60),
        (61, 0, 60, 60),
        (0, 60, 60, 60),
        (0, 61, 60, 60),
        (0, 0, 89_000_001, 60),
        (0, 0, 60, 89_000_001),
        {"left": 0},
        True,
        5,
    ],
)
def test_invalid_crop_values_are_rejected(crop: object) -> None:
    with pytest.raises(PhotoEditError):
        PhotoGeometry(0, crop)  # type: ignore[arg-type]


def test_crop_edge_values_up_to_the_source_limit_are_accepted() -> None:
    assert PhotoGeometry(0, (0, 0, 1, 1)).crop == (0, 0, 1, 1)
    assert PhotoGeometry(0, (88_999_999, 88_999_999, 89_000_000, 89_000_000)).crop is not None


def test_min_crop_size_uses_five_millimetres_at_effective_dpi(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    assert min_crop_size(source) == (59, 59)  # round(5 mm * 300 / 25.4)
    sharp = replace(source, dpi_x=600.0, dpi_y=600.0, effective_dpi=600.0)
    assert min_crop_size(sharp) == (118, 100)  # height is clamped to the source
    mixed = replace(source, dpi_x=300.0, dpi_y=600.0, effective_dpi=600.0)
    assert min_crop_size(mixed) == (118, 100)
    tiny_dpi = replace(source, dpi_x=1.0, dpi_y=1.0, effective_dpi=1.0)
    assert min_crop_size(tiny_dpi) == (1, 1)


def test_min_crop_size_clamps_to_the_source_for_an_absurd_dpi(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    huge = replace(source, dpi_x=1e308, dpi_y=1e308, effective_dpi=1e308)
    assert min_crop_size(huge) == (huge.width, huge.height)


def test_bounds_below_exactly_and_above_the_minimum(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    _recipe(source, PhotoGeometry(0, (0, 0, 59, 59)))
    _recipe(source, PhotoGeometry(0, (101, 41, 160, 100)))
    for crop in ((0, 0, 58, 59), (0, 0, 59, 58), (10, 10, 68, 80), (10, 10, 80, 68)):
        with pytest.raises(PhotoEditError, match="smaller"):
            _recipe(source, PhotoGeometry(0, crop))


@pytest.mark.parametrize("crop", [(0, 0, 161, 60), (0, 0, 60, 101), (100, 0, 161, 100)])
def test_crop_outside_the_source_is_rejected(tmp_path: Path, crop: tuple) -> None:
    with pytest.raises(PhotoEditError):
        _recipe(source_at(tmp_path), PhotoGeometry(0, crop))


def test_full_frame_crop_has_one_encoding(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    with pytest.raises(PhotoEditError, match="full-frame crop must be stored as no crop"):
        _recipe(source, PhotoGeometry(0, (0, 0, WIDTH, HEIGHT)))
    _recipe(source, PhotoGeometry(0, (0, 0, WIDTH, HEIGHT - 1)))


def test_source_smaller_than_the_minimum_admits_only_its_full_extent(tmp_path: Path) -> None:
    source = tone_source(tmp_path, np.zeros((10, 20, 3), dtype=np.uint8))
    assert min_crop_size(source) == (20, 10)
    _recipe(source, PhotoGeometry(2))
    for crop in ((0, 0, 19, 10), (0, 0, 20, 9), (1, 1, 20, 10), (0, 0, 10, 10)):
        with pytest.raises(PhotoEditError):
            _recipe(source, PhotoGeometry(0, crop))
    with pytest.raises(PhotoEditError, match="full-frame"):
        _recipe(source, PhotoGeometry(0, (0, 0, 20, 10)))


@pytest.mark.parametrize("schema", [1, 2])
@pytest.mark.parametrize(
    "geometry",
    [PhotoGeometry(1), PhotoGeometry(0, (0, 0, 80, 80)), PhotoGeometry(3, (5, 5, 90, 90))],
)
def test_older_schemas_cannot_contain_geometry(
    tmp_path: Path, schema: int, geometry: PhotoGeometry
) -> None:
    with pytest.raises(PhotoEditError, match="recipe version cannot contain geometry"):
        _recipe(source_at(tmp_path), geometry, schema)


def test_older_schemas_accept_neutral_geometry_and_v3_accepts_anything_valid(
    tmp_path: Path,
) -> None:
    source = source_at(tmp_path)
    for schema in (1, 2, 3):
        _recipe(source, PhotoGeometry(), schema)
    assert _recipe(source, PhotoGeometry(3, (5, 5, 90, 90))).geometry.quarter_turns == 3


@pytest.mark.parametrize("geometry", [None, (1, None), {"quarter_turns": 1}, 1])
def test_recipe_geometry_must_be_a_photo_geometry_even_in_v3(
    tmp_path: Path, geometry: object
) -> None:
    with pytest.raises(PhotoEditError, match="validated crop and rotation"):
        PhotoEditRecipe(
            source_at(tmp_path),
            schema_version=3,
            algorithm_version="photo-geometry-v1",
            geometry=geometry,  # type: ignore[arg-type]
        )
