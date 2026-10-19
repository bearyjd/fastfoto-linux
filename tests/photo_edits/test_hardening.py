"""Additional hostile-recipe, metadata and publication-boundary evidence."""

import json
from dataclasses import replace
from pathlib import Path
from threading import Event

import numpy as np
import pytest
from PIL import Image, ImageCms

from fastfoto_linux.photo_edits import (
    PREVIEW_MAX_PX,
    EyeEdit,
    PhotoEditCancelledError,
    PhotoEditError,
    PhotoEditRecipe,
    load_source,
    make_preview,
    parse_recipe,
    recipe_bytes,
    save_edit,
    store,
)
from fastfoto_linux.photo_edits import recipe as codec
from tests.photo_edits.helpers import eye, pixels, source_at


@pytest.mark.parametrize("origin", [[], {}, 12, None])
def test_malformed_eye_origin_is_a_domain_error(origin: object) -> None:
    with pytest.raises(PhotoEditError):
        replace(eye(), origin=origin)


@pytest.mark.parametrize("field", ["width", "height", "byte_size", "orientation"])
def test_recipe_source_integer_fields_reject_equal_float_values(tmp_path: Path, field: str) -> None:
    source = source_at(tmp_path)
    payload = json.loads(recipe_bytes(PhotoEditRecipe(source)))
    payload["source"][field] = float(payload["source"][field])
    with pytest.raises(PhotoEditError):
        parse_recipe(json.dumps(payload).encode(), source)


def test_combined_mask_budget_is_checked_before_unpacking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = source_at(tmp_path)
    payload = json.loads(recipe_bytes(PhotoEditRecipe(source, (eye(), eye("second", right=True)))))
    monkeypatch.setattr(codec, "MAX_MASK_PIXELS", 1000)

    def forbid_unpack(*args: object, **kwargs: object) -> None:
        pytest.fail("aggregate mask budget must be checked before decoding any masks")

    monkeypatch.setattr(codec.np, "unpackbits", forbid_unpack)
    with pytest.raises(PhotoEditError):
        parse_recipe(json.dumps(payload).encode(), source)


@pytest.mark.parametrize("corruption", ["invalid-bits", "wrong-shape", "duplicate-id"])
def test_corrupt_mask_or_candidate_identity_is_rejected(tmp_path: Path, corruption: str) -> None:
    source = source_at(tmp_path)
    payload = json.loads(recipe_bytes(PhotoEditRecipe(source, (eye(),))))
    if corruption == "invalid-bits":
        payload["eyes"][0]["mask"]["bits"] = "!" * len(payload["eyes"][0]["mask"]["bits"])
    elif corruption == "wrong-shape":
        payload["eyes"][0]["mask"]["shape"] = [2, 2]
    else:
        payload["eyes"].append(payload["eyes"][0])
    with pytest.raises(PhotoEditError):
        parse_recipe(json.dumps(payload).encode(), source)


def test_arrays_cannot_be_made_writeable_again(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    loaded = load_source(source.path)
    for array in (loaded.pixels, eye().mask):
        with pytest.raises(ValueError):
            array.setflags(write=True)


def test_large_preview_is_reduced_but_preserves_source_dimensions(tmp_path: Path) -> None:
    path = tmp_path / "wide.jpg"
    wide = np.tile(pixels(), (1, 20, 1))
    Image.fromarray(wide).save(path, dpi=(300, 300))
    source = load_source(path)
    preview = make_preview(
        source, PhotoEditRecipe(source), cache_dir=tmp_path / "cache", generation=1, cancel=Event()
    )
    assert preview.source_width == wide.shape[1]
    assert preview.source_height == wide.shape[0]
    assert max(preview.preview_width, preview.preview_height) == PREVIEW_MAX_PX
    with Image.open(preview.after) as image:
        assert image.size == (preview.preview_width, preview.preview_height)


def test_source_modified_during_encode_blocks_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = source_at(tmp_path)
    real_encode = store._encode

    def encode_then_change(*args: object, **kwargs: object) -> bytes:
        data = real_encode(*args, **kwargs)
        source.path.write_bytes(source.path.read_bytes() + b"synthetic concurrent change")
        return data

    monkeypatch.setattr(store, "_encode", encode_then_change)
    with pytest.raises(PhotoEditError, match="source"):
        save_edit(source, PhotoEditRecipe(source), cancel=Event())
    assert not list(tmp_path.glob("*_edit-*"))


def test_valid_icc_profile_is_preserved_without_color_conversion(tmp_path: Path) -> None:
    path = tmp_path / "profile.jpg"
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    Image.fromarray(pixels()).save(path, icc_profile=profile, dpi=(300, 300))
    source = load_source(path)
    assert source.icc_profile == profile
    saved = save_edit(source, PhotoEditRecipe(source), cancel=Event())
    with Image.open(saved.image) as image:
        assert image.info["icc_profile"] == profile


def test_invalid_icc_is_omitted_with_a_visible_warning(tmp_path: Path) -> None:
    path = tmp_path / "invalid-profile.jpg"
    Image.fromarray(pixels()).save(path, icc_profile=b"synthetic invalid profile", dpi=(300, 300))
    source = load_source(path)
    assert source.icc_profile is None
    assert any("profile" in warning.lower() for warning in source.warnings)


def test_nonfinite_and_duplicate_json_fields_are_rejected(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    for data in (b'{"schema_version":NaN}', b'{"schema_version":1,"schema_version":1}'):
        with pytest.raises(PhotoEditError):
            parse_recipe(data, source)


def test_empty_or_non_boolean_mask_is_a_domain_error() -> None:
    for mask in (np.zeros((3, 3), dtype=bool), np.ones((3, 3), dtype=np.uint8)):
        with pytest.raises(PhotoEditError):
            EyeEdit("eye", "manual", (0, 0, 3, 3), (1, 1), mask)


def test_unrepresentable_numeric_coordinate_is_a_domain_error() -> None:
    with pytest.raises(PhotoEditError):
        replace(eye(), center=(10**500, 1))


def test_preview_preserves_valid_color_profile(tmp_path: Path) -> None:
    path = tmp_path / "profile-preview.jpg"
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    Image.fromarray(pixels()).save(path, icc_profile=profile, dpi=(300, 300))
    source = load_source(path)
    preview = make_preview(
        source, PhotoEditRecipe(source), cache_dir=tmp_path / "cache", generation=1, cancel=Event()
    )
    for cached in (preview.before, preview.after):
        with Image.open(cached) as image:
            assert image.info["icc_profile"] == profile


def test_non_rgb_jpeg_is_rejected_without_claiming_a_profile_conversion(tmp_path: Path) -> None:
    path = tmp_path / "cmyk.jpg"
    Image.new("CMYK", (20, 20), (20, 50, 100, 10)).save(path)
    with pytest.raises(PhotoEditError):
        load_source(path)


def test_collision_with_an_uncooperative_writer_retries_without_overwriting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = source_at(tmp_path)
    real_publish = store.write_new_files
    collisions = []

    def collide_once(items: tuple) -> None:
        if not collisions:
            image = items[0][0]
            image.write_bytes(b"external writer owns this name")
            collisions.append(image)
        real_publish(items)

    monkeypatch.setattr(store, "write_new_files", collide_once)
    saved = save_edit(source, PhotoEditRecipe(source), cancel=Event())
    assert saved.image.name.endswith("_edit-0002.jpg")
    assert collisions[0].read_bytes() == b"external writer owns this name"


def test_cancel_arriving_after_encode_does_not_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = source_at(tmp_path)
    cancel = Event()
    real_encode = store._encode

    def encoded_then_cancel(*args: object, **kwargs: object) -> bytes:
        encoded = real_encode(*args, **kwargs)
        cancel.set()
        return encoded

    monkeypatch.setattr(store, "_encode", encoded_then_cancel)
    with pytest.raises(PhotoEditCancelledError):
        save_edit(source, PhotoEditRecipe(source), cancel=cancel)
    assert not list(tmp_path.glob("*_edit-*"))


def test_derivative_size_limit_prevents_an_unreopenable_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = source_at(tmp_path)
    monkeypatch.setattr(store, "MAX_SOURCE_BYTES", 10, raising=False)
    with pytest.raises(PhotoEditError, match=r"large|size|limit"):
        save_edit(source, PhotoEditRecipe(source), cancel=Event())
    assert not list(tmp_path.glob("*_edit-*"))
