"""Bounded recipe decoding and save-new-only derivative publication."""

import hashlib
import io
import struct
from pathlib import Path
from threading import Event

import numpy as np
from PIL import Image, PngImagePlugin

from fastfoto_linux.output.errors import OutputCollisionError
from fastfoto_linux.output.files import locked_folder, write_new_files
from fastfoto_linux.photo_edits.metadata import derivative_exif, derivative_xmp, frame
from fastfoto_linux.photo_edits.model import (
    MAX_RECIPE_BYTES,
    MAX_SOURCE_BYTES,
    PhotoEditError,
    PhotoEditRecipe,
    PhotoSource,
    check_cancel,
    sibling_name,
)
from fastfoto_linux.photo_edits.png_guard import MAX_METADATA_CHUNK
from fastfoto_linux.photo_edits.recipe import (
    fields,
    json_bytes,
    parse_recipe,
    read_object,
    recipe_bytes,
    recipe_object,
)
from fastfoto_linux.photo_edits.render import render
from fastfoto_linux.photo_edits.results import SavedPhotoEdit
from fastfoto_linux.photo_edits.source import load_source, source_bytes, verify_source

MAX_VERSIONS = 9999
XMP_KEY = "XML:com.adobe.xmp"
PNG_COMPRESS_LEVEL = 6
METADATA_TOO_LARGE = "the edited photo metadata is too large to save"
METADATA_UNWRITABLE = "the original's EXIF metadata cannot be rewritten; Save was cancelled"
FORMAT_MISMATCH = "saved photo source and output formats do not match"


def _save_png(
    buffer: io.BytesIO,
    pixels: np.ndarray,
    dpi: tuple[float, float],
    metadata: tuple[bytes, bytes],
    icc_profile: bytes | None,
) -> None:
    exif, xmp = metadata
    info = PngImagePlugin.PngInfo()
    if xmp:
        info.add_itxt(XMP_KEY, xmp.decode("utf-8"))
    Image.fromarray(pixels).save(
        buffer,
        "PNG",
        compress_level=PNG_COMPRESS_LEVEL,
        exif=exif,
        pnginfo=info,
        icc_profile=icc_profile,
        dpi=dpi,
    )


def _metadata(source: PhotoSource, recipe: PhotoEditRecipe) -> tuple[bytes, bytes]:
    """Derivative EXIF and XMP, refused when unwritable or past what the editor itself accepts."""
    try:
        exif = derivative_exif(source, recipe.geometry)
    except (TypeError, ValueError, AttributeError, KeyError, IndexError, struct.error) as error:
        raise PhotoEditError(METADATA_UNWRITABLE) from error
    xmp = derivative_xmp(source, recipe.geometry)
    if len(exif) > MAX_METADATA_CHUNK or len(xmp) > MAX_METADATA_CHUNK:
        raise PhotoEditError(METADATA_TOO_LARGE)
    return exif, xmp


def _encode(source: PhotoSource, recipe: PhotoEditRecipe, cancel: Event) -> bytes:
    pixels = render(source, recipe, cancel=cancel)
    check_cancel(cancel)
    *_, dpi_x, dpi_y = frame(source, recipe.geometry)
    metadata = _metadata(source, recipe)
    buffer = io.BytesIO()
    if source.format == "PNG":
        _save_png(buffer, pixels, (dpi_x, dpi_y), metadata, source.icc_profile)
        check_cancel(cancel)
        return buffer.getvalue()
    Image.fromarray(pixels).save(
        buffer,
        "JPEG",
        quality=recipe.quality,
        subsampling=0,
        exif=metadata[0],
        xmp=metadata[1],
        icc_profile=source.icc_profile,
        dpi=(dpi_x, dpi_y),
    )
    check_cancel(cancel)
    return buffer.getvalue()


def _targets(source: PhotoSource, version: int) -> tuple[Path, Path]:
    basename = f"{source.path.stem}_edit-{version:04d}"
    ext = ".png" if source.format == "PNG" else ".jpg"
    return source.path.with_name(basename + ext), source.path.with_name(basename + ".json")


def _taken(source: PhotoSource, version: int) -> bool:
    """A number is used when any sibling revision exists, whatever its format."""
    stem = f"{source.path.stem}_edit-{version:04d}"
    names = (stem + ext for ext in (".jpg", ".png", ".json"))
    return any((path := source.path.with_name(n)).exists() or path.is_symlink() for n in names)


def save_edit(source: PhotoSource, recipe: PhotoEditRecipe, *, cancel: Event) -> SavedPhotoEdit:
    """Write a new numbered copy (the master's format) and sidecar; the sidecar commits it."""
    check_cancel(cancel)
    verify_source(source)
    encoded = _encode(source, recipe, cancel)
    if len(encoded) > MAX_SOURCE_BYTES:
        raise PhotoEditError("edited photo exceeds the supported file size limit")
    with locked_folder(source.path.parent):
        check_cancel(cancel)
        verify_source(source)
        for version in range(1, MAX_VERSIONS + 1):
            image, sidecar = _targets(source, version)
            if _taken(source, version):
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
    if image.suffix.lower() != (".png" if source.format == "PNG" else ".jpg"):
        raise PhotoEditError(FORMAT_MISMATCH)
    recipe = parse_recipe(data, source)
    if hashlib.sha256(source_bytes(image)).hexdigest() != output["sha256"]:
        raise PhotoEditError("saved derivative output hash changed")
    return source, recipe


__all__ = ["open_edit", "parse_recipe", "recipe_bytes", "save_edit"]
