"""Schema 3 parsing, byte identity, update rules and literal legacy fixtures."""

import hashlib
import json
import shutil
from pathlib import Path
from threading import Event

import pytest

from fastfoto_linux.photo_edits import (
    PhotoEditError,
    PhotoEditRecipe,
    PhotoGeometry,
    PhotoTone,
    open_edit,
    parse_recipe,
    recipe_bytes,
    render,
    update_geometry,
    update_tone,
)
from fastfoto_linux.photo_edits import recipe as codec
from tests.photo_edits.geometry_helpers import TONE, geometry_recipe
from tests.photo_edits.helpers import HEIGHT, WIDTH, eye, source_at

FIXTURES = Path(__file__).parent / "fixtures"
CROPPED = PhotoGeometry(1, (10, 5, 100, 80))


def v3_payload(tmp_path: Path) -> tuple[object, dict]:
    source = source_at(tmp_path)
    recipe = geometry_recipe(source, CROPPED, eyes=(eye(),), tone=TONE)
    return source, json.loads(recipe_bytes(recipe))


def encode(payload: dict) -> bytes:
    return codec.json_bytes(payload)


def test_v3_bytes_have_the_exact_shape_and_round_trip(tmp_path: Path) -> None:
    source, payload = v3_payload(tmp_path)
    assert (payload["schema_version"], payload["algorithm_version"]) == (3, "photo-geometry-v1")
    assert payload["geometry"] == {"crop": [10, 5, 100, 80], "quarter_turns": 1}
    assert set(payload) == {
        "schema_version",
        "algorithm_version",
        "quality",
        "source",
        "eyes",
        "tone",
        "geometry",
    }
    data = encode(payload)
    restored = parse_recipe(data, source)
    assert restored.geometry == CROPPED and restored.tone == TONE
    assert isinstance(restored.geometry.crop, tuple)
    assert recipe_bytes(restored) == data


def test_neutral_v3_round_trips_with_a_null_crop(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    recipe = update_geometry(geometry_recipe(source, CROPPED), PhotoGeometry())
    data = recipe_bytes(recipe)
    assert json.loads(data)["geometry"] == {"crop": None, "quarter_turns": 0}
    assert recipe_bytes(parse_recipe(data, source)) == data


def test_v1_and_v2_bytes_never_contain_geometry(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    assert "geometry" not in json.loads(recipe_bytes(PhotoEditRecipe(source)))
    v1 = PhotoEditRecipe(source, schema_version=1, algorithm_version="redeye-v1")
    assert set(json.loads(recipe_bytes(v1))) == {
        "schema_version",
        "algorithm_version",
        "quality",
        "source",
        "eyes",
    }


@pytest.mark.parametrize("schema", [1, 2])
def test_geometry_key_is_rejected_in_older_schemas(tmp_path: Path, schema: int) -> None:
    source, payload = v3_payload(tmp_path)
    payload = {
        **payload,
        "schema_version": schema,
        "algorithm_version": {1: "redeye-v1", 2: "photo-tone-v1"}[schema],
    }
    if schema == 1:
        payload.pop("tone")
    with pytest.raises(PhotoEditError, match="photo recipe"):
        parse_recipe(encode(payload), source)
    with pytest.raises(PhotoEditError, match="photo recipe"):
        codec.read_object(encode(payload))


def test_v3_requires_tone_and_geometry_and_no_extra_root_keys(tmp_path: Path) -> None:
    source, payload = v3_payload(tmp_path)
    for missing in ("geometry", "tone"):
        broken = {key: value for key, value in payload.items() if key != missing}
        with pytest.raises(PhotoEditError, match="photo recipe"):
            parse_recipe(encode(broken), source)
    with pytest.raises(PhotoEditError, match="photo recipe"):
        parse_recipe(encode({**payload, "extra": 1}), source)


@pytest.mark.parametrize(
    "geometry",
    [
        None,
        [],
        {},
        {"quarter_turns": 1},
        {"crop": None},
        {"quarter_turns": 1, "crop": None, "extra": 0},
        {"quarter_turns": 1, "crop": [10, 5, 100, 80], "angle": 0},
    ],
)
def test_geometry_needs_exactly_its_two_keys(tmp_path: Path, geometry: object) -> None:
    source, payload = v3_payload(tmp_path)
    with pytest.raises(PhotoEditError):
        parse_recipe(encode({**payload, "geometry": geometry}), source)


@pytest.mark.parametrize(
    "crop",
    [
        [10, 5, 100],
        [10, 5, 100, 80, 1],
        [],
        {"left": 10},
        True,
        7,
        "10,5,100,80",
        [10, 5, 100, True],
        [10, 5, 100.0, 80],
        [10, 5, "100", 80],
        [10, 5, None, 80],
        [100, 5, 10, 80],
        [10, 80, 100, 5],
        [10, 5, 100, 101],
        [10, 5, 161, 80],
        [0, 0, 20, 20],
        [0, 0, WIDTH, HEIGHT],
        [-1, 0, 100, 80],
    ],
)
def test_invalid_crop_payloads_are_rejected(tmp_path: Path, crop: object) -> None:
    source, payload = v3_payload(tmp_path)
    geometry = {"quarter_turns": 1, "crop": crop}
    with pytest.raises(PhotoEditError):
        parse_recipe(encode({**payload, "geometry": geometry}), source)


@pytest.mark.parametrize("turns", [True, False, 1.0, 4, -1, "1", None, [1]])
def test_invalid_quarter_turn_payloads_are_rejected(tmp_path: Path, turns: object) -> None:
    source, payload = v3_payload(tmp_path)
    geometry = {"quarter_turns": turns, "crop": None}
    with pytest.raises(PhotoEditError):
        parse_recipe(encode({**payload, "geometry": geometry}), source)


@pytest.mark.parametrize(
    ("schema", "algorithm"),
    [(3, "photo-tone-v1"), (2, "photo-geometry-v1"), (4, "photo-geometry-v1")],
)
def test_mismatched_versions_fail_before_any_mask_is_decoded(
    tmp_path: Path, schema: int, algorithm: str
) -> None:
    source, payload = v3_payload(tmp_path)
    payload["eyes"] = [{"garbage": True}]
    payload["schema_version"], payload["algorithm_version"] = schema, algorithm
    for call in (codec.read_object, lambda d: parse_recipe(d, source)):
        with pytest.raises(
            PhotoEditError, match=r"unsupported photo correction algorithm|schema version"
        ):
            call(encode(payload))


def test_geometry_is_validated_against_the_source_on_parse(tmp_path: Path) -> None:
    source, payload = v3_payload(tmp_path)
    payload["geometry"]["crop"] = [0, 0, 58, 59]
    with pytest.raises(PhotoEditError, match="smaller"):
        parse_recipe(encode(payload), source)


def test_update_geometry_type_checks_both_arguments(tmp_path: Path) -> None:
    recipe = PhotoEditRecipe(source_at(tmp_path))
    with pytest.raises(PhotoEditError):
        update_geometry("recipe", PhotoGeometry())  # type: ignore[arg-type]
    with pytest.raises(PhotoEditError):
        update_geometry(recipe, None)  # type: ignore[arg-type]
    with pytest.raises(PhotoEditError):
        update_geometry(recipe, (1, None))  # type: ignore[arg-type]


def test_update_geometry_returns_the_same_object_for_no_change(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    recipe = PhotoEditRecipe(source)
    assert update_geometry(recipe, PhotoGeometry()) is recipe
    assert update_geometry(recipe, PhotoGeometry(0, (0, 0, WIDTH, HEIGHT))) is recipe
    cropped = geometry_recipe(source, CROPPED)
    assert update_geometry(cropped, PhotoGeometry(1, (10, 5, 100, 80))) is cropped


@pytest.mark.parametrize("schema", [1, 2])
def test_update_geometry_upgrades_older_drafts_without_mutating_them(
    tmp_path: Path, schema: int
) -> None:
    source = source_at(tmp_path)
    algorithm = {1: "redeye-v1", 2: "photo-tone-v1"}[schema]
    tone = TONE if schema == 2 else PhotoTone()
    recipe = PhotoEditRecipe(source, (eye(),), schema, algorithm, quality=80, tone=tone)
    upgraded = update_geometry(recipe, CROPPED)
    assert (upgraded.schema_version, upgraded.algorithm_version) == (3, "photo-geometry-v1")
    assert upgraded.geometry == CROPPED
    assert (upgraded.source, upgraded.eyes, upgraded.tone, upgraded.quality) == (
        source,
        recipe.eyes,
        tone,
        80,
    )
    assert (recipe.schema_version, recipe.geometry) == (schema, PhotoGeometry())


def test_update_geometry_rejects_invalid_crops_through_the_recipe(tmp_path: Path) -> None:
    recipe = PhotoEditRecipe(source_at(tmp_path))
    with pytest.raises(PhotoEditError):
        update_geometry(recipe, PhotoGeometry(0, (0, 0, 20, 20)))
    with pytest.raises(PhotoEditError):
        update_geometry(recipe, PhotoGeometry(0, (0, 0, 200, 80)))


def test_full_frame_input_clears_an_existing_crop_and_stays_v3(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    cropped = geometry_recipe(source, PhotoGeometry(2, (10, 5, 100, 80)))
    cleared = update_geometry(cropped, PhotoGeometry(2, (0, 0, WIDTH, HEIGHT)))
    assert cleared.geometry == PhotoGeometry(2, None) and cleared.schema_version == 3
    assert cropped.geometry.crop == (10, 5, 100, 80)


def test_v3_stays_v3_when_returned_to_neutral(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    cropped = geometry_recipe(source, CROPPED)
    neutral = update_geometry(cropped, PhotoGeometry())
    assert neutral.geometry == PhotoGeometry()
    assert (neutral.schema_version, neutral.algorithm_version) == (3, "photo-geometry-v1")
    assert cropped.geometry == CROPPED
    assert update_geometry(neutral, PhotoGeometry()) is neutral


def test_update_tone_never_downgrades_v3_and_still_upgrades_v1(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    v3 = geometry_recipe(source, CROPPED)
    toned = update_tone(v3, TONE)
    assert (toned.schema_version, toned.algorithm_version) == (3, "photo-geometry-v1")
    assert toned.geometry == CROPPED and toned.tone == TONE
    assert update_tone(toned, TONE) is toned
    v1 = PhotoEditRecipe(source, schema_version=1, algorithm_version="redeye-v1")
    assert update_tone(v1, PhotoTone()) is v1
    upgraded = update_tone(v1, TONE)
    assert (upgraded.schema_version, upgraded.algorithm_version) == (2, "photo-tone-v1")
    v2 = PhotoEditRecipe(source)
    assert update_tone(v2, TONE).schema_version == 2


def _copy_fixture(tmp_path: Path, name: str, output: str) -> Path:
    shutil.copyfile(FIXTURES / "legacy.jpg", tmp_path / "legacy.jpg")
    shutil.copyfile(FIXTURES / "legacy.jpg", tmp_path / output)
    shutil.copyfile(FIXTURES / name, tmp_path / name)
    return tmp_path / name


def test_literal_v2_fixture_is_canonical_with_nonneutral_tone() -> None:
    raw = (FIXTURES / "legacy-v2.json").read_bytes()
    payload = json.loads(raw)
    assert codec.json_bytes(payload) == raw
    assert (payload["schema_version"], payload["algorithm_version"]) == (2, "photo-tone-v1")
    assert payload["tone"] == {"brightness": 25, "contrast": -35, "saturation": 60, "strength": 75}
    assert "geometry" not in payload
    assert payload["output"] == {
        "name": "legacy_edit-0001.jpg",
        "sha256": hashlib.sha256((FIXTURES / "legacy.jpg").read_bytes()).hexdigest(),
    }
    assert payload["eyes"][0]["id"] == "legacy-eye"


@pytest.mark.parametrize("name", ["legacy-v1.json", "legacy-v2.json"])
def test_legacy_fixtures_reopen_byte_identically_and_stay_unchanged(
    tmp_path: Path, name: str
) -> None:
    sidecar = _copy_fixture(tmp_path, name, "legacy_edit-0001.jpg")
    frozen = sidecar.read_bytes()
    source_before = (tmp_path / "legacy.jpg").read_bytes()
    source, recipe = open_edit(sidecar)
    expected = json.loads(frozen)
    expected.pop("output")
    assert recipe_bytes(recipe) == codec.json_bytes(expected)
    assert recipe.geometry == PhotoGeometry()
    assert update_geometry(recipe, PhotoGeometry()) is recipe
    render(source, recipe, cancel=Event())
    assert sidecar.read_bytes() == frozen
    assert (tmp_path / "legacy.jpg").read_bytes() == source_before
