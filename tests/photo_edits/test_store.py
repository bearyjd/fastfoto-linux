"""Bounded source-bound recipes and save-new-only publication."""

import json
from dataclasses import replace
from pathlib import Path
from threading import Event

import numpy as np
import pytest
from PIL import ExifTags, Image

from fastfoto_linux.output import files
from fastfoto_linux.photo_edits import (
    MAX_EYES,
    MAX_MASK_PIXELS,
    MAX_RECIPE_BYTES,
    EyeEdit,
    PhotoEditCancelledError,
    PhotoEditError,
    PhotoEditRecipe,
    load_source,
    open_edit,
    parse_recipe,
    recipe_bytes,
    render,
    save_edit,
)
from tests.photo_edits.helpers import DPI, LEFT, eye, pixels, source_at


def test_recipe_round_trip_preserves_masks_decisions_strength_and_pixels(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    recipe = PhotoEditRecipe(source, (eye(strength=45), eye("right", right=True, accepted=False)))
    encoded = recipe_bytes(recipe)
    decoded = parse_recipe(encoded, source)
    assert decoded.schema_version == 1 and decoded.algorithm_version == "redeye-v1"
    assert [edit.accepted for edit in decoded.eyes] == [True, False]
    assert decoded.eyes[0].strength == 45
    assert np.array_equal(decoded.eyes[0].mask, recipe.eyes[0].mask)
    assert not decoded.eyes[0].mask.flags.writeable
    assert np.array_equal(
        render(source, recipe, cancel=Event()), render(source, decoded, cancel=Event())
    )
    payload = json.loads(encoded)
    assert payload["source"]["name"] == source.path.name
    assert payload["source"]["sha256"] == source.sha256
    assert str(tmp_path).encode() not in encoded


@pytest.mark.parametrize("schema", [0, 2, True, "1"])
def test_unknown_or_invalid_schema_is_rejected(tmp_path: Path, schema: object) -> None:
    source = source_at(tmp_path)
    data = json.dumps({"schema_version": schema}).encode()
    with pytest.raises(PhotoEditError):
        parse_recipe(data, source)


@pytest.mark.parametrize("name", ["../other.jpg", "/other.jpg", "sub/other.jpg", ".."])
def test_recipe_source_cannot_escape_its_sibling_folder(tmp_path: Path, name: str) -> None:
    source = source_at(tmp_path)
    payload = json.loads(recipe_bytes(PhotoEditRecipe(source)))
    payload["source"]["name"] = name
    with pytest.raises(PhotoEditError):
        parse_recipe(json.dumps(payload).encode(), source)


def test_recipe_decode_is_bounded_before_decoding_masks(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    with pytest.raises(PhotoEditError):
        parse_recipe(b" " * (MAX_RECIPE_BYTES + 1), source)
    recipe = PhotoEditRecipe(source, (eye(),))
    payload = json.loads(recipe_bytes(recipe))
    payload["eyes"][0]["mask"]["shape"] = [MAX_MASK_PIXELS + 1, MAX_MASK_PIXELS + 1]
    with pytest.raises(PhotoEditError):
        parse_recipe(json.dumps(payload).encode(), source)


def test_too_many_candidates_and_duplicate_ids_are_rejected(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    with pytest.raises(PhotoEditError):
        recipe_bytes(PhotoEditRecipe(source, tuple(eye(str(i)) for i in range(MAX_EYES + 1))))
    with pytest.raises(PhotoEditError):
        recipe_bytes(PhotoEditRecipe(source, (eye(), eye())))


@pytest.mark.parametrize("strength", [-1, 101, True, float("nan")])
def test_invalid_strength_is_rejected(tmp_path: Path, strength: int) -> None:
    source = source_at(tmp_path)
    with pytest.raises(PhotoEditError):
        recipe_bytes(PhotoEditRecipe(source, (replace(eye(), strength=strength),)))


def test_mask_ownership_is_immutable_at_public_boundary() -> None:
    mask = np.ones((3, 3), dtype=bool)
    edit = EyeEdit("eye", "manual", (0, 0, 3, 3), (1, 1), mask)
    mask[:] = False
    assert edit.mask.all()
    assert not edit.mask.flags.writeable


def test_save_twice_creates_new_versions_and_reopen_replays_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = source_at(tmp_path)
    original = source.path.read_bytes()
    enhanced = source.path.with_name("photo_0001_a.jpg")
    back = source.path.with_name("photo_0001_b.jpg")
    enhanced.write_bytes(b"existing enhanced")
    back.write_bytes(b"existing back")
    recipe = PhotoEditRecipe(source, (eye(),))
    first = save_edit(source, recipe, cancel=Event())
    second = save_edit(source, recipe, cancel=Event())
    assert first.image.name == "photo_0001_edit-0001.jpg"
    assert first.sidecar.name == "photo_0001_edit-0001.json"
    assert second.image.name == "photo_0001_edit-0002.jpg"
    assert first.image.exists() and first.sidecar.exists()
    assert source.path.read_bytes() == original
    assert enhanced.read_bytes() == b"existing enhanced" and back.read_bytes() == b"existing back"

    def no_detection(*args: object, **kwargs: object) -> None:
        pytest.fail("reopening a saved edit must not run the detector")

    monkeypatch.setattr("fastfoto_linux.enhance.redeye.detect_faces_full_res", no_detection)
    reopened_source, reopened = open_edit(first.sidecar)
    assert np.array_equal(
        render(reopened_source, reopened, cancel=Event()), render(source, recipe, cancel=Event())
    )


def test_changed_source_blocks_save_and_reopen(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    recipe = PhotoEditRecipe(source, (eye(),))
    saved = save_edit(source, recipe, cancel=Event())
    source.path.write_bytes(b"changed retained source")
    with pytest.raises(PhotoEditError, match=r"source|hash|changed"):
        save_edit(source, recipe, cancel=Event())
    with pytest.raises(PhotoEditError, match=r"source|hash|changed"):
        open_edit(saved.sidecar)


def test_changed_derivative_is_rejected_on_reopen(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    saved = save_edit(source, PhotoEditRecipe(source, (eye(),)), cancel=Event())
    saved.image.write_bytes(b"changed derivative")
    with pytest.raises(PhotoEditError, match=r"derivative|hash|changed|output"):
        open_edit(saved.sidecar)


def test_orphan_derivative_reserves_version_without_becoming_a_saved_edit(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    orphan = tmp_path / "photo_0001_edit-0001.jpg"
    orphan.write_bytes(b"orphan version")
    saved = save_edit(source, PhotoEditRecipe(source, (eye(),)), cancel=Event())
    assert saved.image.name == "photo_0001_edit-0002.jpg"
    assert orphan.read_bytes() == b"orphan version"


def test_publication_failure_rolls_back_pair_and_preserves_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = source_at(tmp_path)
    original = source.path.read_bytes()
    real_publish = files._publish
    published = []

    def fail_sidecar(entry: object) -> None:
        published.append(entry.target.suffix)
        if entry.target.suffix == ".json":
            raise OSError("synthetic sidecar publication failure")
        real_publish(entry)

    monkeypatch.setattr(files, "_publish", fail_sidecar)
    with pytest.raises(OSError, match="synthetic"):
        save_edit(source, PhotoEditRecipe(source, (eye(),)), cancel=Event())
    assert published == [".jpg", ".json"]
    assert not list(tmp_path.glob("*_edit-*"))
    assert not list(tmp_path.glob("*.tmp"))
    assert source.path.read_bytes() == original


def test_cancel_before_publication_preserves_existing_files(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    original = source.path.read_bytes()
    cancel = Event()
    cancel.set()
    with pytest.raises(PhotoEditCancelledError):
        save_edit(source, PhotoEditRecipe(source, (eye(),)), cancel=cancel)
    assert source.path.read_bytes() == original
    assert not list(tmp_path.glob("*_edit-*"))


def test_derivative_preserves_metadata_and_normalizes_orientation(tmp_path: Path) -> None:
    path = tmp_path / "metadata.jpg"
    exif = Image.Exif()
    exif[ExifTags.Base.Orientation] = 6
    exif[ExifTags.Base.ImageDescription] = "Synthetic note"
    xmp = b'<x:xmpmeta xmlns:x="adobe:ns:meta/"/>'
    Image.fromarray(pixels()).save(path, exif=exif, xmp=xmp, dpi=(DPI, DPI))
    before = path.read_bytes()
    source = load_source(path)
    edit = eye()
    edit = replace(edit, center=LEFT, accepted=False)
    saved = save_edit(source, PhotoEditRecipe(source, (edit,)), cancel=Event())
    with Image.open(saved.image) as image:
        assert image.getexif().get(ExifTags.Base.Orientation, 1) == 1
        assert image.getexif()[ExifTags.Base.ImageDescription] == "Synthetic note"
        assert image.info["xmp"] == xmp
        assert image.info["dpi"] == (DPI, DPI)
        assert image.size == (source.width, source.height)
    assert path.read_bytes() == before
