"""Schema 6: serialization, strict parsing, version pairs and the update rule."""

import json
from pathlib import Path

import pytest

from fastfoto_linux.photo_edits import (
    PhotoDetail,
    PhotoEditError,
    PhotoEditRecipe,
    PhotoGeometry,
    PhotoTone,
    PhotoWhiteBalance,
    parse_recipe,
    recipe_bytes,
    update_detail,
    update_geometry,
    update_tone,
    update_white_balance,
)
from fastfoto_linux.photo_edits import recipe as codec
from tests.photo_edits.helpers import eye, source_at
from tests.photo_edits.straighten_helpers import TONE, straight_recipe

V6 = (6, "photo-detail-v1")
WB = PhotoWhiteBalance(10, -20)
DETAIL = PhotoDetail(20, 30, 40)


def _v5(tmp_path: Path) -> tuple[object, PhotoEditRecipe]:
    source = source_at(tmp_path)
    base = straight_recipe(source, PhotoGeometry(1, (3, 4, 100, 70), 37), tone=TONE, eyes=(eye(),))
    return source, update_white_balance(base, WB)


def _v6(tmp_path: Path) -> tuple[object, PhotoEditRecipe]:
    source, recipe = _v5(tmp_path)
    return source, update_detail(recipe, DETAIL)


def _payload(tmp_path: Path) -> tuple[object, dict]:
    source, recipe = _v6(tmp_path)
    return source, json.loads(recipe_bytes(recipe))


def test_v6_serializes_exactly_the_three_keys_and_round_trips(tmp_path: Path) -> None:
    source, recipe = _v6(tmp_path)
    data = recipe_bytes(recipe)
    payload = json.loads(data)
    assert (payload["schema_version"], payload["algorithm_version"]) == V6
    assert payload["detail"] == {"denoise_chroma": 30, "denoise_luma": 20, "sharpen": 40}
    assert b'"detail":{"denoise_chroma":30,"denoise_luma":20,"sharpen":40}' in data
    again = parse_recipe(data, source)
    assert recipe_bytes(again) == data
    assert again.detail == DETAIL and again.white_balance == WB and again.tone == TONE


def test_v6_keeps_the_angle_and_white_balance_through_a_round_trip(tmp_path: Path) -> None:
    source, recipe = _v6(tmp_path)
    payload = json.loads(recipe_bytes(recipe))
    assert payload["geometry"]["straighten_tenths"] == 37
    assert payload["white_balance"] == {"temperature": 10, "tint": -20}
    again = parse_recipe(recipe_bytes(recipe), source)
    assert again.geometry.straighten_tenths == 37 and again.white_balance == WB


def test_neutral_v6_still_writes_the_key(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    recipe = PhotoEditRecipe(source, (), *V6)
    data = recipe_bytes(recipe)
    assert b'"detail":{"denoise_chroma":0,"denoise_luma":0,"sharpen":0}' in data
    assert parse_recipe(data, source).detail == PhotoDetail()


@pytest.mark.parametrize("schema", [2, 3, 4, 5])
def test_older_schemas_write_no_detail_key(tmp_path: Path, schema: int) -> None:
    older = PhotoEditRecipe(source_at(tmp_path), (), schema, codec.RECIPE_VERSIONS[schema])
    assert "detail" not in json.loads(recipe_bytes(older))


@pytest.mark.parametrize("schema", [2, 3, 4, 5])
def test_older_schemas_reject_a_detail_key(tmp_path: Path, schema: int) -> None:
    source = source_at(tmp_path)
    payload = json.loads(
        recipe_bytes(PhotoEditRecipe(source, (), schema, codec.RECIPE_VERSIONS[schema]))
    )
    assert parse_recipe(codec.json_bytes(payload), source).detail == PhotoDetail()
    payload["detail"] = {"denoise_luma": 0, "denoise_chroma": 0, "sharpen": 0}
    with pytest.raises(PhotoEditError, match="invalid photo recipe fields"):
        parse_recipe(codec.json_bytes(payload), source)


def test_v6_requires_the_detail_key(tmp_path: Path) -> None:
    source, payload = _payload(tmp_path)
    del payload["detail"]
    with pytest.raises(PhotoEditError, match="photo recipe"):
        parse_recipe(codec.json_bytes(payload), source)


def test_extra_or_missing_subkeys_are_rejected(tmp_path: Path) -> None:
    source, payload = _payload(tmp_path)
    extra = {**payload, "detail": {**payload["detail"], "extra": 1}}
    with pytest.raises(PhotoEditError, match="detail"):
        parse_recipe(codec.json_bytes(extra), source)
    for key in payload["detail"]:
        short = {k: v for k, v in payload["detail"].items() if k != key}
        with pytest.raises(PhotoEditError, match="detail"):
            parse_recipe(codec.json_bytes({**payload, "detail": short}), source)
    with pytest.raises(PhotoEditError, match="detail"):
        parse_recipe(codec.json_bytes({**payload, "detail": [20, 30, 40]}), source)


@pytest.mark.parametrize("bad", [True, 1.5, 101, -1, "3", None])
@pytest.mark.parametrize("key", ["denoise_luma", "denoise_chroma", "sharpen"])
def test_bad_values_are_rejected(tmp_path: Path, key: str, bad: object) -> None:
    source, payload = _payload(tmp_path)
    broken = {**payload, "detail": {**payload["detail"], key: bad}}
    with pytest.raises(PhotoEditError):
        parse_recipe(codec.json_bytes(broken), source)


def test_giant_duplicate_and_nonfinite_literals_are_rejected(tmp_path: Path) -> None:
    source, payload = _payload(tmp_path)
    data = codec.json_bytes(payload)
    needle = b'"sharpen":40'
    assert data.count(needle) == 1
    for literal in (b'"sharpen":1e999', b'"sharpen":NaN', b'"sharpen":40,"sharpen":40'):
        with pytest.raises(PhotoEditError):
            parse_recipe(data.replace(needle, literal), source)


@pytest.mark.parametrize("pair", [(6, "photo-color-v1"), (5, "photo-detail-v1")])
def test_mismatched_version_pairs_fail_before_masks_are_decoded(
    tmp_path: Path, pair: tuple[int, str]
) -> None:
    _, payload = _payload(tmp_path)
    payload["eyes"][0]["mask"]["bits"] = "!!!!"
    payload.update(schema_version=pair[0], algorithm_version=pair[1])
    with pytest.raises(PhotoEditError, match="algorithm version"):
        codec.read_object(codec.json_bytes(payload))


def test_read_checked_returns_the_detail_as_the_fifth_item(tmp_path: Path) -> None:
    _, recipe = _v6(tmp_path)
    checked = codec._read_checked(recipe_bytes(recipe))
    assert len(checked) == 5 and checked[4] == DETAIL
    _, older = _v5(tmp_path)
    assert codec._read_checked(recipe_bytes(older))[4] == PhotoDetail()


def test_update_detail_no_op_returns_the_same_object(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    plain = PhotoEditRecipe(source)
    assert update_detail(plain, PhotoDetail()) is plain
    _, v6 = _v6(tmp_path)
    assert update_detail(v6, DETAIL) is v6


def test_update_detail_upgrades_without_mutating_the_input(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    plain = PhotoEditRecipe(source)
    upgraded = update_detail(plain, DETAIL)
    assert (upgraded.schema_version, upgraded.algorithm_version) == V6
    assert (plain.schema_version, plain.detail) == (2, PhotoDetail())
    _, v5 = _v5(tmp_path)
    v6 = update_detail(v5, DETAIL)
    assert v6.schema_version == 6 and v6.white_balance == WB
    assert v6.geometry.straighten_tenths == 37 and v5.schema_version == 5


def test_a_v6_draft_never_downgrades(tmp_path: Path) -> None:
    _, v6 = _v6(tmp_path)
    neutral = update_detail(v6, PhotoDetail())
    assert neutral.schema_version == 6 and neutral.detail == PhotoDetail()
    assert update_white_balance(v6, PhotoWhiteBalance()).schema_version == 6
    assert update_tone(v6, PhotoTone()).schema_version == 6
    assert update_geometry(v6, PhotoGeometry()).schema_version == 6
    assert update_white_balance(v6, PhotoWhiteBalance(5, 5)).schema_version == 6


def test_a_neutral_detail_does_not_upgrade_a_draft(tmp_path: Path) -> None:
    _, v5 = _v5(tmp_path)
    assert update_detail(v5, PhotoDetail()) is v5


def test_update_detail_checks_types(tmp_path: Path) -> None:
    recipe = PhotoEditRecipe(source_at(tmp_path))
    with pytest.raises(PhotoEditError):
        update_detail(recipe, (1, 2, 3))  # type: ignore[arg-type]
    with pytest.raises(PhotoEditError):
        update_detail("recipe", PhotoDetail())  # type: ignore[arg-type]
