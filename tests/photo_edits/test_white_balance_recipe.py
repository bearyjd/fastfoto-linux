"""Schema 5: serialization, strict parsing, version pairs and the update rule."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from fastfoto_linux.photo_edits import (
    PhotoEditError,
    PhotoEditRecipe,
    PhotoGeometry,
    PhotoWhiteBalance,
    parse_recipe,
    recipe_bytes,
    update_geometry,
    update_tone,
    update_white_balance,
)
from fastfoto_linux.photo_edits import recipe as codec
from tests.photo_edits.helpers import eye, source_at
from tests.photo_edits.straighten_helpers import TONE, straight_recipe

V4 = (4, "photo-geometry-v2")
V5 = (5, "photo-color-v1")
WB = PhotoWhiteBalance(10, -20)


def _v5(tmp_path: Path, balance: PhotoWhiteBalance = WB) -> tuple[object, PhotoEditRecipe]:
    source = source_at(tmp_path)
    base = straight_recipe(source, PhotoGeometry(1, (3, 4, 100, 70), 37), tone=TONE, eyes=(eye(),))
    # Go through a non-neutral balance: only that upgrades a draft, and a v5 draft never drops.
    return source, update_white_balance(update_white_balance(base, WB), balance)


def _payload(tmp_path: Path) -> tuple[object, dict]:
    source, recipe = _v5(tmp_path)
    return source, json.loads(recipe_bytes(recipe))


def test_v5_serializes_exactly_the_two_controls_and_round_trips(tmp_path: Path) -> None:
    source, recipe = _v5(tmp_path)
    payload = json.loads(recipe_bytes(recipe))
    assert (payload["schema_version"], payload["algorithm_version"]) == V5
    assert payload["white_balance"] == {"temperature": 10, "tint": -20}
    data = recipe_bytes(recipe)
    assert b'"white_balance":{"temperature":10,"tint":-20}' in data
    again = parse_recipe(data, source)
    assert recipe_bytes(again) == data
    assert again.white_balance == WB and again.tone == TONE
    assert again.geometry == recipe.geometry and again.eyes[0].id == "left"


def test_v5_keeps_the_straighten_angle_through_a_round_trip(tmp_path: Path) -> None:
    source, recipe = _v5(tmp_path)
    assert json.loads(recipe_bytes(recipe))["geometry"]["straighten_tenths"] == 37
    assert parse_recipe(recipe_bytes(recipe), source).geometry.straighten_tenths == 37


def test_neutral_v5_still_writes_the_key(tmp_path: Path) -> None:
    source, recipe = _v5(tmp_path, PhotoWhiteBalance())
    assert json.loads(recipe_bytes(recipe))["white_balance"] == {"temperature": 0, "tint": 0}
    assert parse_recipe(recipe_bytes(recipe), source).white_balance == PhotoWhiteBalance()


def test_older_payloads_never_gain_the_key(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    v2 = PhotoEditRecipe(source)
    v4 = straight_recipe(source, PhotoGeometry(0, None, 5))
    for recipe in (v2, v4):
        assert "white_balance" not in json.loads(recipe_bytes(recipe))


@pytest.mark.parametrize(
    "version", [(2, "photo-tone-v1"), (3, "photo-geometry-v1"), (4, "photo-geometry-v2")]
)
def test_older_schemas_reject_the_key(tmp_path: Path, version: tuple[int, str]) -> None:
    source, payload = _payload(tmp_path)
    payload.update(schema_version=version[0], algorithm_version=version[1])
    if version[0] < 4:
        del payload["geometry"]["straighten_tenths"]
    with pytest.raises(PhotoEditError, match="photo recipe"):
        parse_recipe(codec.json_bytes(payload), source)


def test_v5_requires_the_key(tmp_path: Path) -> None:
    source, payload = _payload(tmp_path)
    del payload["white_balance"]
    with pytest.raises(PhotoEditError, match="photo recipe"):
        parse_recipe(codec.json_bytes(payload), source)


def test_a_missing_or_extra_subkey_is_rejected(tmp_path: Path) -> None:
    source, payload = _payload(tmp_path)
    for broken in ({"temperature": 1}, {"temperature": 1, "tint": 2, "extra": 3}, {}, [1, 2], None):
        with pytest.raises(PhotoEditError, match="white balance"):
            parse_recipe(codec.json_bytes({**payload, "white_balance": broken}), source)


@pytest.mark.parametrize("bad", [True, 1.5, 101, -101, "3", None, [1], {"a": 1}])
@pytest.mark.parametrize("field", ["temperature", "tint"])
def test_bad_control_values_are_rejected(tmp_path: Path, field: str, bad: object) -> None:
    source, payload = _payload(tmp_path)
    broken = {**payload, "white_balance": {**payload["white_balance"], field: bad}}
    with pytest.raises(PhotoEditError):
        parse_recipe(codec.json_bytes(broken), source)


def _raw_with(tmp_path: Path, old: bytes, new: bytes) -> tuple[object, bytes]:
    source, recipe = _v5(tmp_path)
    data = recipe_bytes(recipe)
    assert old in data
    return source, data.replace(old, new)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (b'"tint":-20', b'"tint":1e999'),
        (b'"tint":-20', b'"tint":NaN'),
        (b'"tint":-20', b'"tint":Infinity'),
        (b'"tint":-20', b'"tint":-20.0'),
        (b'"tint":-20', b'"tint":true'),
        (b'"temperature":10,', b'"temperature":10,"temperature":10,'),
        (b'"white_balance":{', b'"white_balance":{},"white_balance":{'),
        (b'"tint":-20', b'"tint":' + b"9" * 5000),
    ],
)
def test_hostile_literals_are_rejected(tmp_path: Path, old: bytes, new: bytes) -> None:
    source, data = _raw_with(tmp_path, old, new)
    with pytest.raises(PhotoEditError):
        parse_recipe(data, source)


@pytest.mark.parametrize(("schema", "algorithm"), [(5, "photo-geometry-v2"), (4, "photo-color-v1")])
def test_mismatched_version_pairs_fail_before_masks_are_decoded(
    tmp_path: Path, schema: int, algorithm: str
) -> None:
    _, payload = _payload(tmp_path)
    payload["eyes"][0]["mask"]["bits"] = "!!!!"
    payload.update(schema_version=schema, algorithm_version=algorithm)
    with pytest.raises(PhotoEditError, match="algorithm version"):
        codec.read_object(codec.json_bytes(payload))


def test_update_white_balance_noop_returns_the_same_object(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    v2 = PhotoEditRecipe(source)
    assert update_white_balance(v2, PhotoWhiteBalance()) is v2
    _, v5 = _v5(tmp_path)
    assert update_white_balance(v5, WB) is v5


def test_update_white_balance_schema_rules(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    v2 = PhotoEditRecipe(source)
    up = update_white_balance(v2, WB)
    assert (up.schema_version, up.algorithm_version) == V5 and up.white_balance == WB
    assert (v2.schema_version, v2.white_balance) == (2, PhotoWhiteBalance())  # not mutated
    angled = straight_recipe(source, PhotoGeometry(0, None, 37))
    from_v4 = update_white_balance(angled, WB)
    assert from_v4.schema_version == 5 and from_v4.geometry.straighten_tenths == 37
    back = update_white_balance(up, PhotoWhiteBalance())
    assert (back.schema_version, back.algorithm_version) == V5 and back is not up
    assert update_tone(up, TONE).schema_version == 5
    assert update_geometry(up, PhotoGeometry(1)).schema_version == 5
    assert (
        update_white_balance(update_geometry(v2, PhotoGeometry(1)), WB).geometry.quarter_turns == 1
    )


def test_a_neutral_update_on_an_older_draft_does_not_upgrade(tmp_path: Path) -> None:
    v4 = straight_recipe(source_at(tmp_path), PhotoGeometry(0, None, 5))
    assert update_white_balance(v4, PhotoWhiteBalance()) is v4


@pytest.mark.parametrize("bad", [None, (1, 2), {"temperature": 1, "tint": 1}, 3])
def test_update_white_balance_type_checks(tmp_path: Path, bad: object) -> None:
    with pytest.raises(PhotoEditError, match="white balance"):
        update_white_balance(PhotoEditRecipe(source_at(tmp_path)), bad)  # type: ignore[arg-type]
    with pytest.raises(PhotoEditError, match="white balance"):
        update_white_balance(bad, WB)  # type: ignore[arg-type]


def test_a_legacy_draft_upgrades_only_through_the_update_function(
    tmp_path: Path,
) -> None:
    legacy = PhotoEditRecipe(source_at(tmp_path), (), 1, "redeye-v1")
    with pytest.raises(PhotoEditError):
        replace(legacy, white_balance=WB)
    up = update_white_balance(legacy, WB)
    assert up.schema_version == 5
