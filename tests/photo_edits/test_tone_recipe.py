"""Strict v1/v2 migration, literal legacy replay and source-based tone persistence."""

import hashlib
import importlib
import json
import shutil
from pathlib import Path
from threading import Event

import numpy as np
import pytest
from PIL import ExifTags, Image, ImageCms

from fastfoto_linux.photo_edits import (
    MAX_RECIPE_BYTES,
    PhotoEditError,
    PhotoEditRecipe,
    PhotoTone,
    load_source,
    make_preview,
    open_edit,
    parse_recipe,
    recipe_bytes,
    render,
    save_edit,
    update_tone,
)
from tests.photo_edits.helpers import eye, pixels, source_at
from tests.photo_edits.tone_helpers import reference_tone

codec = importlib.import_module("fastfoto_linux.photo_edits.recipe")
renderer = importlib.import_module("fastfoto_linux.photo_edits.render")
store = importlib.import_module("fastfoto_linux.photo_edits.store")
FIXTURES = Path(__file__).parent / "fixtures"
TONE = {"brightness": 25, "contrast": -35, "saturation": 60, "strength": 75}


def v2_payload(source: object) -> dict:
    payload = json.loads(recipe_bytes(PhotoEditRecipe(source, (eye(),), 1, "redeye-v1")))
    return {
        **payload,
        "schema_version": 2,
        "algorithm_version": "photo-tone-v1",
        "tone": TONE.copy(),
    }


def test_literal_v1_saved_fixture_reopens_without_migration_or_rewrite(tmp_path: Path) -> None:
    for name in ("legacy.jpg", "legacy-v1.json"):
        shutil.copyfile(FIXTURES / name, tmp_path / name)
    shutil.copyfile(FIXTURES / "legacy.jpg", tmp_path / "legacy_edit-0001.jpg")
    sidecar = tmp_path / "legacy-v1.json"
    frozen_bytes = sidecar.read_bytes()
    source_bytes = (tmp_path / "legacy.jpg").read_bytes()
    source, recipe = open_edit(sidecar)
    assert (recipe.schema_version, recipe.algorithm_version, recipe.tone) == (
        1,
        "redeye-v1",
        PhotoTone(),
    )
    assert recipe.eyes[0].accepted and recipe.eyes[0].id == "legacy-eye"
    assert np.array_equal(render(source, recipe, cancel=Event()), np.full((3, 3, 3), 10, np.uint8))
    original_payload = json.loads(frozen_bytes)
    original_payload.pop("output")
    assert json.loads(recipe_bytes(recipe)) == original_payload
    assert update_tone(recipe, PhotoTone()) is recipe
    assert sidecar.read_bytes() == frozen_bytes
    assert source.path.read_bytes() == source_bytes


def test_v2_round_trip_preserves_all_controls_and_exact_render(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    tone = PhotoTone(**TONE)
    recipe = PhotoEditRecipe(source, (eye(), eye("right", right=True, accepted=False)), tone=tone)
    data = recipe_bytes(recipe)
    payload = json.loads(data)
    assert payload.get("tone") == TONE
    assert (payload["schema_version"], payload["algorithm_version"]) == (2, "photo-tone-v1")
    assert set(payload) == {
        "schema_version",
        "algorithm_version",
        "quality",
        "source",
        "eyes",
        "tone",
    }
    restored = parse_recipe(data, source)
    assert restored.tone == tone and restored.eyes[1].accepted is False
    assert recipe_bytes(restored) == data
    assert np.array_equal(
        render(source, recipe, cancel=Event()), render(source, restored, cancel=Event())
    )


@pytest.mark.parametrize(
    "tone",
    [
        None,
        [],
        {},
        {**TONE, "extra": 1},
        {key: value for key, value in TONE.items() if key != "strength"},
        {**TONE, "brightness": True},
        {**TONE, "contrast": 0.0},
        {**TONE, "saturation": 101},
        {**TONE, "strength": -1},
        {**TONE, "brightness": "1"},
    ],
)
def test_v2_rejects_exact_tone_shape_or_invalid_values(tmp_path: Path, tone: object) -> None:
    source = source_at(tmp_path)
    payload = {**v2_payload(source), "tone": tone}
    with pytest.raises(PhotoEditError):
        parse_recipe(json.dumps(payload).encode(), source)


@pytest.mark.parametrize(
    "schema,algorithm,include_tone",
    [
        (1, "photo-tone-v1", False),
        (2, "redeye-v1", True),
        (3, "photo-tone-v1", True),
        (True, "redeye-v1", False),
        (1, "redeye-v1", True),
        (2, "photo-tone-v1", False),
    ],
)
def test_invalid_headers_fail_before_mask_decode_or_source_allocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    schema: object,
    algorithm: str,
    include_tone: bool,
) -> None:
    source = source_at(tmp_path)
    payload = v2_payload(source)
    payload.update(schema_version=schema, algorithm_version=algorithm)
    if not include_tone:
        payload.pop("tone")
    payload["output"] = {"name": "synthetic-edit.jpg", "sha256": "0" * 64}
    data = json.dumps(payload).encode()

    def forbidden_allocation(*args: object, **kwargs: object) -> None:
        pytest.fail("invalid version/tone headers must fail before decoding source or masks")

    monkeypatch.setattr(codec, "_mask", forbidden_allocation)
    monkeypatch.setattr(store, "load_source", forbidden_allocation)
    with pytest.raises(PhotoEditError):
        parse_recipe(data, source)
    sidecar = tmp_path / "invalid.json"
    sidecar.write_bytes(data)
    with pytest.raises(PhotoEditError):
        open_edit(sidecar)


@pytest.mark.parametrize(
    "bad", [b'"brightness":NaN', b'"brightness":Infinity', b'"brightness":0,"brightness":1']
)
def test_v2_rejects_nonfinite_or_duplicate_tone_json(tmp_path: Path, bad: bytes) -> None:
    source = source_at(tmp_path)
    data = json.dumps(v2_payload(source), separators=(",", ":")).encode()
    data = data.replace(b'"brightness":25', bad)
    with pytest.raises(PhotoEditError):
        parse_recipe(data, source)


@pytest.mark.parametrize("invalid_tone", [None, {**TONE, "brightness": True}, {**TONE, "extra": 1}])
def test_invalid_tone_header_rejected_before_source_decode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, invalid_tone: object
) -> None:
    payload = v2_payload(source_at(tmp_path))
    payload["tone"] = invalid_tone
    payload["output"] = {"name": "synthetic-edit.jpg", "sha256": "0" * 64}
    sidecar = tmp_path / "invalid-tone.json"
    sidecar.write_text(json.dumps(payload))

    def forbidden_decode(*args: object, **kwargs: object) -> None:
        pytest.fail("invalid tone headers must fail before source decoding")

    monkeypatch.setattr(store, "load_source", forbidden_decode)
    with pytest.raises(PhotoEditError):
        open_edit(sidecar)


def test_v2_rejects_oversized_input(tmp_path: Path) -> None:
    with pytest.raises(PhotoEditError):
        parse_recipe(b" " * (MAX_RECIPE_BYTES + 1), source_at(tmp_path))


def test_v2_missing_tone_and_legacy_extra_tone_are_rejected(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    payload = v2_payload(source)
    payload.pop("tone")
    with pytest.raises(PhotoEditError):
        parse_recipe(json.dumps(payload).encode(), source)
    payload.update(schema_version=1, algorithm_version="redeye-v1", tone=dict.fromkeys(TONE, 0))
    with pytest.raises(PhotoEditError):
        parse_recipe(json.dumps(payload).encode(), source)


def test_v2_rejects_wrong_retained_source_hash(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    payload = v2_payload(source)
    payload["source"]["sha256"] = "0" * 64
    with pytest.raises(PhotoEditError, match=r"source|hash"):
        parse_recipe(json.dumps(payload).encode(), source)


def test_save_reopen_replays_source_and_persists_tone_without_redetection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = source_at(tmp_path)
    original_bytes = source.path.read_bytes()
    original_pixels = source.pixels.copy()
    recipe = PhotoEditRecipe(source, (eye(),), tone=PhotoTone(**TONE))
    first = save_edit(source, recipe, cancel=Event())
    assert json.loads(first.sidecar.read_bytes()).get("tone") == TONE

    def forbidden_detection(*args: object, **kwargs: object) -> None:
        pytest.fail("tone replay must not detect eyes again")

    monkeypatch.setattr("fastfoto_linux.enhance.redeye.detect_faces_full_res", forbidden_detection)
    reopened_source, reopened = open_edit(first.sidecar)
    assert reopened.source.path == source.path and reopened.tone == recipe.tone
    assert np.array_equal(
        render(source, recipe, cancel=Event()), render(reopened_source, reopened, cancel=Event())
    )
    second = save_edit(reopened_source, reopened, cancel=Event())
    assert first.image != second.image and first.image.read_bytes() == second.image.read_bytes()
    assert source.path.read_bytes() == original_bytes
    assert np.array_equal(source.pixels, original_pixels)
    first.image.write_bytes(b"synthetic corrupt derivative")
    with pytest.raises(PhotoEditError, match=r"output|hash|derivative"):
        open_edit(first.sidecar)


def test_preview_and_export_share_full_resolution_tone_and_preserve_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "metadata-tone.jpg"
    exif = Image.Exif()
    exif[ExifTags.Base.ImageDescription] = "Synthetic tone metadata"
    xmp = b'<x:xmpmeta xmlns:x="adobe:ns:meta/"/>'
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    Image.fromarray(pixels()).save(path, exif=exif, xmp=xmp, icc_profile=icc, dpi=(300, 600))
    original_bytes = path.read_bytes()
    original_hash = hashlib.sha256(original_bytes).hexdigest()
    source = load_source(path)
    tone = PhotoTone(**TONE)
    recipe = PhotoEditRecipe(source, (eye(),), tone=tone)
    corrected = render(source, PhotoEditRecipe(source, recipe.eyes, 1, "redeye-v1"), cancel=Event())
    expected = reference_tone(corrected, tone)
    seen = []
    original_preview = renderer._preview_jpeg

    def inspect_preview(rgb: np.ndarray, *, bounded: bool, icc_profile: bytes | None) -> tuple:
        seen.append(rgb.copy())
        assert icc_profile == icc
        return original_preview(rgb, bounded=bounded, icc_profile=icc_profile)

    monkeypatch.setattr(renderer, "_preview_jpeg", inspect_preview)
    preview = make_preview(
        source,
        recipe,
        cache_dir=tmp_path / "cache",
        generation=3,
        cancel=Event(),
        selected_id="left",
    )
    assert np.array_equal(seen[0], source.pixels)
    assert np.array_equal(seen[1], expected)
    x0, y0, x1, y1 = recipe.eyes[0].roi
    assert np.array_equal(seen[3], expected[y0:y1, x0:x1])
    saved = save_edit(source, recipe, cancel=Event())
    for output in (preview.before, preview.after, preview.roi_after, saved.image):
        with Image.open(output) as image:
            assert image.info["icc_profile"] == icc
    with Image.open(saved.image) as image:
        assert image.getexif()[ExifTags.Base.ImageDescription] == "Synthetic tone metadata"
        assert image.info["xmp"] == xmp and image.info["dpi"] == (300, 600)
        assert image.getexif().get(ExifTags.Base.Orientation, 1) == 1
    assert source.sha256 == original_hash and path.read_bytes() == original_bytes
    assert source.icc_profile == icc and source.xmp == xmp
