"""Schema 4: validation, parsing, byte identity, update rules and the literal v3 fixture."""

import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from fastfoto_linux.photo_edits.straighten import straightened_size

import fastfoto_linux.photo_edits as package
from fastfoto_linux.photo_edits import (
    PhotoEditError,
    PhotoEditRecipe,
    PhotoGeometry,
    PhotoTone,
    frame_size,
    min_crop_size,
    model,
    open_edit,
    parse_recipe,
    recipe_bytes,
    render,
    update_geometry,
    update_tone,
)
from fastfoto_linux.photo_edits import recipe as codec
from tests.photo_edits.helpers import eye, source_at
from tests.photo_edits.straighten_helpers import TONE, straight_recipe

FIXTURES = Path(__file__).parent / "fixtures"
V4 = (4, "photo-geometry-v2")


def test_constants_and_exports() -> None:
    assert (model.STRAIGHTEN_SCHEMA_VERSION, model.STRAIGHTEN_ALGORITHM_VERSION) == V4
    assert model.RECIPE_VERSIONS[4] == "photo-geometry-v2"
    assert (model.SCHEMA_VERSION, model.ALGORITHM_VERSION) == (2, "photo-tone-v1")
    for name in ("straightened_size", "frame_size", "STRAIGHTEN_SCHEMA_VERSION"):
        assert name in package.__all__ and hasattr(package, name)
    assert package.STRAIGHTEN_ALGORITHM_VERSION == "photo-geometry-v2"


@pytest.mark.parametrize("value", [True, 2.5, 151, -151, "3", None])
def test_angle_must_be_an_integer_in_range(value: object) -> None:
    with pytest.raises(PhotoEditError, match="straighten"):
        PhotoGeometry(0, None, value)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [-150, -1, 0, 1, 150])
def test_angle_limits_are_accepted_and_positional_meaning_is_unchanged(value: int) -> None:
    assert PhotoGeometry(1, (1, 2, 3, 4), value).straighten_tenths == value
    assert PhotoGeometry(2).straighten_tenths == 0


def test_frame_size_and_minimum_crop_use_the_straightened_frame(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    geometry = PhotoGeometry(0, None, 37)
    assert frame_size(source, geometry) == straightened_size(160, 100, 37)
    assert frame_size(source, PhotoGeometry()) == (160, 100)
    assert min_crop_size(source) == min_crop_size(source, PhotoGeometry())
    fast = replace(source, dpi_x=600.0, dpi_y=600.0, effective_dpi=600.0)
    fw, fh = straightened_size(160, 100, 150)
    assert min_crop_size(fast) == (118, 100)
    assert min_crop_size(fast, PhotoGeometry(0, None, 150)) == (min(118, fw), min(118, fh))


def test_schema_below_four_cannot_hold_an_angle(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    for version in ((3, "photo-geometry-v1"), (2, "photo-tone-v1"), (1, "redeye-v1")):
        with pytest.raises(PhotoEditError, match="cannot contain straighten"):
            PhotoEditRecipe(source, (), *version, geometry=PhotoGeometry(0, None, 5))
    ok = PhotoEditRecipe(source, (), *V4, geometry=PhotoGeometry(0, None, 5))
    assert ok.geometry.straighten_tenths == 5


def test_non_square_pixels_reject_an_angle(tmp_path: Path) -> None:
    source = replace(source_at(tmp_path), dpi_x=300.0, dpi_y=150.0)
    assert PhotoEditRecipe(source, (), *V4, geometry=PhotoGeometry(0, None, 0))
    with pytest.raises(PhotoEditError, match="square pixels"):
        PhotoEditRecipe(source, (), *V4, geometry=PhotoGeometry(0, None, 1))


def test_an_angle_that_leaves_less_than_five_millimetres_is_rejected(tmp_path: Path) -> None:
    fast = replace(source_at(tmp_path), dpi_x=600.0, dpi_y=600.0, effective_dpi=600.0)
    assert PhotoEditRecipe(fast, (), *V4, geometry=PhotoGeometry(0, None, 0))
    with pytest.raises(PhotoEditError, match="less than the 5 mm minimum"):
        PhotoEditRecipe(fast, (), *V4, geometry=PhotoGeometry(0, None, 150))
    source = source_at(tmp_path)  # 300 dpi: the 148 by 63 frame still holds 59 px
    assert PhotoEditRecipe(source, (), *V4, geometry=PhotoGeometry(0, None, 150))


def test_crop_is_validated_inside_the_straightened_frame(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    fw, fh = straightened_size(160, 100, 37)
    base = {"source": source, "eyes": (), "schema_version": 4, "algorithm_version": V4[1]}

    def make(crop: tuple[int, int, int, int]) -> PhotoEditRecipe:
        return PhotoEditRecipe(**base, geometry=PhotoGeometry(0, crop, 37))

    assert make((0, 0, fw - 1, fh)).geometry.crop == (0, 0, fw - 1, fh)
    with pytest.raises(PhotoEditError, match="outside"):
        make((0, 0, fw + 1, fh))
    with pytest.raises(PhotoEditError, match="outside"):
        make((0, 0, fw, fh + 1))
    with pytest.raises(PhotoEditError, match="full-frame"):
        make((0, 0, fw, fh))
    min_w, min_h = min_crop_size(source, PhotoGeometry(0, None, 37))
    with pytest.raises(PhotoEditError, match="minimum"):
        make((0, 0, min_w - 1, fh))
    assert make((0, 0, min_w, min_h))


def _payload(tmp_path: Path, tenths: int = 37) -> tuple[object, dict]:
    source = source_at(tmp_path)
    recipe = straight_recipe(
        source, PhotoGeometry(1, (3, 4, 100, 50), tenths), tone=TONE, eyes=(eye(),)
    )
    return source, json.loads(recipe_bytes(recipe))


def test_v4_serializes_the_exact_geometry_object_and_round_trips(tmp_path: Path) -> None:
    source, payload = _payload(tmp_path)
    assert (payload["schema_version"], payload["algorithm_version"]) == V4
    assert payload["geometry"] == {
        "crop": [3, 4, 100, 50],
        "quarter_turns": 1,
        "straighten_tenths": 37,
    }
    data = codec.json_bytes(payload)
    assert b'"geometry":{"crop":[3,4,100,50],"quarter_turns":1,"straighten_tenths":37}' in data
    recipe = parse_recipe(data, source)
    assert recipe.geometry == PhotoGeometry(1, (3, 4, 100, 50), 37)
    assert recipe_bytes(recipe) == data
    uncropped = straight_recipe(source, PhotoGeometry(0, None, -150))
    assert b'"geometry":{"crop":null,"quarter_turns":0,"straighten_tenths":-150}' in recipe_bytes(
        uncropped
    )


def test_v3_payload_never_gains_the_key(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    v3 = straight_recipe(source, PhotoGeometry(1, (3, 4, 100, 50)))
    assert v3.schema_version == 3
    assert "straighten_tenths" not in json.loads(recipe_bytes(v3))["geometry"]


def test_parser_rejects_the_key_in_v3_and_a_missing_or_extra_key_in_v4(tmp_path: Path) -> None:
    source, payload = _payload(tmp_path)
    v3 = {**payload, "schema_version": 3, "algorithm_version": "photo-geometry-v1"}
    with pytest.raises(PhotoEditError, match="geometry"):
        parse_recipe(codec.json_bytes(v3), source)
    missing = {**payload, "geometry": {"crop": None, "quarter_turns": 0}}
    with pytest.raises(PhotoEditError, match="geometry"):
        parse_recipe(codec.json_bytes(missing), source)
    extra = {**payload, "geometry": {**payload["geometry"], "extra": 1}}
    with pytest.raises(PhotoEditError, match="geometry"):
        parse_recipe(codec.json_bytes(extra), source)
    for bad in (True, 1.5, 151, "3", None):
        broken = {**payload, "geometry": {**payload["geometry"], "straighten_tenths": bad}}
        with pytest.raises(PhotoEditError):
            parse_recipe(codec.json_bytes(broken), source)


@pytest.mark.parametrize(
    ("schema", "algorithm"), [(4, "photo-geometry-v1"), (3, "photo-geometry-v2")]
)
def test_mismatched_version_pairs_fail_before_masks_are_decoded(
    tmp_path: Path, schema: int, algorithm: str
) -> None:
    _, payload = _payload(tmp_path)
    payload["eyes"][0]["mask"]["bits"] = "!!!!"
    payload.update(schema_version=schema, algorithm_version=algorithm)
    with pytest.raises(PhotoEditError, match="algorithm version"):
        codec.read_object(codec.json_bytes(payload))


def test_v4_requires_geometry_and_v2_rejects_it(tmp_path: Path) -> None:
    source, payload = _payload(tmp_path)
    del payload["geometry"]
    with pytest.raises(PhotoEditError, match="photo recipe"):
        parse_recipe(codec.json_bytes(payload), source)
    _, again = _payload(tmp_path)
    v2 = {**again, "schema_version": 2, "algorithm_version": "photo-tone-v1"}
    with pytest.raises(PhotoEditError, match="photo recipe"):
        parse_recipe(codec.json_bytes(v2), source)


def test_update_geometry_schema_rules(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    v2 = PhotoEditRecipe(source)
    angled = update_geometry(v2, PhotoGeometry(0, None, 37))
    assert (angled.schema_version, angled.algorithm_version) == V4
    v3 = update_geometry(v2, PhotoGeometry(1, (3, 4, 100, 50)))
    assert v3.schema_version == 3
    assert update_geometry(v3, PhotoGeometry(2, (3, 4, 100, 50))).schema_version == 3
    from_v3 = update_geometry(v3, PhotoGeometry(1, None, -5))
    assert (from_v3.schema_version, from_v3.algorithm_version) == V4
    neutral = update_geometry(angled, PhotoGeometry())
    assert (neutral.schema_version, neutral.geometry) == (4, PhotoGeometry())
    back_to_zero = update_geometry(angled, PhotoGeometry(1))
    assert back_to_zero.schema_version == 4 and back_to_zero.geometry.straighten_tenths == 0
    assert update_tone(angled, TONE).schema_version == 4
    assert update_geometry(angled, angled.geometry) is angled
    assert update_geometry(v2, PhotoGeometry()) is v2
    assert v2.schema_version == 2 and v3.schema_version == 3  # inputs are never mutated


def test_a_full_straightened_frame_crop_is_stored_as_none(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    fw, fh = straightened_size(160, 100, 37)
    recipe = update_geometry(PhotoEditRecipe(source), PhotoGeometry(1, (0, 0, fw, fh), 37))
    assert recipe.geometry == PhotoGeometry(1, None, 37)
    zero = update_geometry(PhotoEditRecipe(source), PhotoGeometry(1, (0, 0, 160, 100)))
    assert zero.geometry == PhotoGeometry(1)
    same = update_geometry(recipe, PhotoGeometry(1, (0, 0, fw, fh), 37))
    assert same is recipe


def test_update_geometry_rejects_a_crop_valid_only_in_the_source(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    with pytest.raises(PhotoEditError, match="outside"):
        update_geometry(PhotoEditRecipe(source), PhotoGeometry(0, (0, 0, 160, 99), 150))


def test_v4_at_zero_renders_byte_equal_to_the_equivalent_v3(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    v3 = straight_recipe(source, PhotoGeometry(1, (10, 5, 100, 80)), tone=TONE, eyes=(eye(),))
    v4 = replace(v3, schema_version=4, algorithm_version=V4[1])
    assert (
        render(source, v3, cancel=Event()).tobytes() == render(source, v4, cancel=Event()).tobytes()
    )
    assert json.loads(recipe_bytes(v4))["geometry"]["straighten_tenths"] == 0


def test_literal_v3_fixture_is_canonical_and_reopens_byte_identically(tmp_path: Path) -> None:
    raw = (FIXTURES / "legacy-v3.json").read_bytes()
    payload = json.loads(raw)
    assert codec.json_bytes(payload) == raw
    assert (payload["schema_version"], payload["algorithm_version"]) == (3, "photo-geometry-v1")
    assert payload["geometry"] == {"crop": [2, 1, 10, 7], "quarter_turns": 1}
    assert payload["tone"] != {"brightness": 0, "contrast": 0, "saturation": 0, "strength": 100}
    assert payload["eyes"][0]["id"] == "legacy-eye"
    digest = hashlib.sha256((FIXTURES / "legacy-v3.jpg").read_bytes()).hexdigest()
    assert payload["output"] == {"name": "legacy_edit-0001.jpg", "sha256": digest}
    for name in ("legacy-v3.jpg", "legacy-v3.json"):
        shutil.copyfile(FIXTURES / name, tmp_path / name)
    shutil.copyfile(FIXTURES / "legacy-v3.jpg", tmp_path / "legacy_edit-0001.jpg")
    source, recipe = open_edit(tmp_path / "legacy-v3.json")
    expected = {key: value for key, value in payload.items() if key != "output"}
    assert recipe_bytes(recipe) == codec.json_bytes(expected)
    assert update_geometry(recipe, recipe.geometry) is recipe
    assert recipe.schema_version == 3 and recipe.tone != PhotoTone()
    render(source, recipe, cancel=Event())
    assert (tmp_path / "legacy-v3.json").read_bytes() == raw


def test_older_fixtures_are_byte_for_byte_unchanged() -> None:
    pinned = {"legacy-v1.json": "dceabcf408a69ca0", "legacy-v2.json": "dc20902cb666d82c"}
    for name, prefix in pinned.items():
        assert hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest().startswith(prefix)
