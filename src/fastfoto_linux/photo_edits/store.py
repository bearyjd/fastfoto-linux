"""Bounded recipe decoding and save-new-only derivative publication."""

import hashlib
import io
from pathlib import Path
from threading import Event

from PIL import Image

from fastfoto_linux.output.errors import OutputCollisionError
from fastfoto_linux.output.files import locked_folder, write_new_files
from fastfoto_linux.photo_edits.metadata import derivative_exif, derivative_xmp, frame
from fastfoto_linux.photo_edits.model import (
    MAX_RECIPE_BYTES,
    MAX_SOURCE_BYTES,
    PhotoEditError,
    PhotoEditRecipe,
    PhotoSource,
    SavedPhotoEdit,
    sibling_name,
)
from fastfoto_linux.photo_edits.recipe import (
    fields,
    json_bytes,
    parse_recipe,
    read_object,
    recipe_bytes,
    recipe_object,
)
from fastfoto_linux.photo_edits.render import check_cancel, render
from fastfoto_linux.photo_edits.source import load_source, source_bytes, verify_source

MAX_VERSIONS = 9999


def _encode(source: PhotoSource, recipe: PhotoEditRecipe, cancel: Event) -> bytes:
    pixels = render(source, recipe, cancel=cancel)
    check_cancel(cancel)
    *_, dpi_x, dpi_y = frame(source, recipe.geometry)
    buffer = io.BytesIO()
    Image.fromarray(pixels).save(
        buffer,
        "JPEG",
        quality=recipe.quality,
        subsampling=0,
        exif=derivative_exif(source, recipe.geometry),
        xmp=derivative_xmp(source, recipe.geometry),
        icc_profile=source.icc_profile,
        dpi=(dpi_x, dpi_y),
    )
    check_cancel(cancel)
    return buffer.getvalue()


def _targets(source: PhotoSource, version: int) -> tuple[Path, Path]:
    basename = f"{source.path.stem}_edit-{version:04d}"
    return source.path.with_name(basename + ".jpg"), source.path.with_name(basename + ".json")


def save_edit(source: PhotoSource, recipe: PhotoEditRecipe, *, cancel: Event) -> SavedPhotoEdit:
    """Write a new numbered JPEG and sidecar, with sidecar as the commit marker."""
    check_cancel(cancel)
    verify_source(source)
    encoded = _encode(source, recipe, cancel)
    if len(encoded) > MAX_SOURCE_BYTES:
        raise PhotoEditError("edited JPEG exceeds the supported file size limit")
    with locked_folder(source.path.parent):
        check_cancel(cancel)
        verify_source(source)
        for version in range(1, MAX_VERSIONS + 1):
            image, sidecar = _targets(source, version)
            if image.exists() or image.is_symlink() or sidecar.exists() or sidecar.is_symlink():
                continue
            payload = recipe_object(recipe)
            payload["output"] = {"name": image.name, "sha256": hashlib.sha256(encoded).hexdigest()}
            manifest = json_bytes(payload)
            check_cancel(cancel)
            try:
                write_new_files(((image, encoded), (sidecar, manifest)))
            except OutputCollisionError:
                continue
            return SavedPhotoEdit(image, sidecar, recipe)
    raise PhotoEditError("no free photo edit revision number remains")


def _read_sidecar(sidecar: Path) -> bytes:
    try:
        with sidecar.open("rb") as stream:
            data = stream.read(MAX_RECIPE_BYTES + 1)
    except OSError as error:
        raise PhotoEditError("the saved photo recipe cannot be read") from error
    if len(data) > MAX_RECIPE_BYTES:
        raise PhotoEditError("the saved photo recipe exceeds its byte limit")
    return data


def _sibling(sidecar: Path, name: object) -> Path:
    sibling = sidecar.parent / sibling_name(name)
    if sibling.is_symlink() or sibling.resolve().parent != sidecar.parent.resolve():
        raise PhotoEditError("saved photo source and output must be sibling files")
    return sibling


def open_edit(sidecar: Path) -> tuple[PhotoSource, PhotoEditRecipe]:
    """Verify source and derivative identities, then reopen without re-detecting eyes."""
    sidecar = sidecar.absolute()
    data = _read_sidecar(sidecar)
    payload = read_object(data)
    output = fields(payload.get("output"), {"name", "sha256"}, "saved output identity")
    original = payload["source"]
    if not isinstance(original, dict):
        raise PhotoEditError("saved photo source identity is invalid")
    source_path = _sibling(sidecar, original.get("name"))
    image = _sibling(sidecar, output["name"])
    if image in (source_path, sidecar):
        raise PhotoEditError("saved derivative must be distinct from its source and sidecar")
    source = load_source(source_path, expected_sha256=original.get("sha256"))
    recipe = parse_recipe(data, source)
    if hashlib.sha256(source_bytes(image)).hexdigest() != output["sha256"]:
        raise PhotoEditError("saved derivative output hash changed")
    return source, recipe


__all__ = ["open_edit", "parse_recipe", "recipe_bytes", "save_edit"]
