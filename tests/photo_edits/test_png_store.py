"""PNG in, PNG out: the edit keeps the master's format, metadata and 600 dpi."""

import hashlib
import json
import struct
from dataclasses import replace
from pathlib import Path
from threading import Event

import numpy as np
import pytest
from PIL import Image

from fastfoto_linux.photo_edits import (
    PhotoEditError,
    load_source,
    open_edit,
    recipe_bytes,
    save_edit,
)
from fastfoto_linux.photo_edits.model import PhotoEditRecipe
from fastfoto_linux.photo_edits.png_guard import MAX_XMP_PACKET
from tests.photo_edits import png_helpers as h
from tests.photo_edits.helpers import source_at


def _master(tmp_path: Path) -> Path:
    path = tmp_path / "photo_0001.png"
    path.write_bytes(h.master_png())
    return path


def _recipe(source) -> PhotoEditRecipe:
    return PhotoEditRecipe(source)


def test_saving_a_png_master_writes_a_png_edit_with_metadata(tmp_path: Path) -> None:
    source = load_source(_master(tmp_path))
    saved = save_edit(source, _recipe(source), cancel=Event())
    assert saved.image.name == "photo_0001_edit-0001.png"
    assert saved.sidecar.name == "photo_0001_edit-0001.json"
    with Image.open(saved.image) as out:
        out.load()
        assert out.format == "PNG" and out.mode == "RGB"
        assert round(out.info["dpi"][0]) == 600
        assert "XML:com.adobe.xmp" in out.info
        assert out.getexif().get(274) == 1
        assert np.array_equal(np.array(out), h.pixels())


def test_open_edit_round_trips_a_png_master(tmp_path: Path) -> None:
    source = load_source(_master(tmp_path))
    recipe = _recipe(source)
    saved = save_edit(source, recipe, cancel=Event())
    reopened, again = open_edit(saved.sidecar)
    assert reopened.sha256 == source.sha256
    assert recipe_bytes(again) == recipe_bytes(recipe)


def test_version_numbers_are_shared_between_jpg_and_png(tmp_path: Path) -> None:
    source = load_source(_master(tmp_path))
    (tmp_path / "photo_0001_edit-0001.jpg").write_bytes(b"x")
    assert save_edit(source, _recipe(source), cancel=Event()).image.name.endswith("0002.png")
    (tmp_path / "photo_0001_edit-0003.png").write_bytes(b"x")
    assert save_edit(source, _recipe(source), cancel=Event()).image.name.endswith("0004.png")


def test_a_jpeg_master_still_saves_a_jpeg(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    saved = save_edit(source, _recipe(source), cancel=Event())
    assert saved.image.suffix == ".jpg"


def test_a_jpeg_master_skips_numbers_taken_by_a_png_edit(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    (tmp_path / "photo_0001_edit-0001.png").write_bytes(b"x")
    assert save_edit(source, _recipe(source), cancel=Event()).image.name.endswith("0002.jpg")


def test_open_edit_reports_the_png_format_and_an_equal_recipe(tmp_path: Path) -> None:
    source = load_source(_master(tmp_path))
    recipe = _recipe(source)
    reopened, again = open_edit(save_edit(source, recipe, cancel=Event()).sidecar)
    assert reopened.format == "PNG"
    assert recipe_bytes(again) == recipe_bytes(recipe)


def test_a_tampered_png_output_is_refused_on_reopen(tmp_path: Path) -> None:
    source = load_source(_master(tmp_path))
    saved = save_edit(source, _recipe(source), cancel=Event())
    saved.image.write_bytes(saved.image.read_bytes() + b"x")
    with pytest.raises(PhotoEditError, match="output hash changed"):
        open_edit(saved.sidecar)


def test_a_sidecar_pairing_a_png_source_with_a_jpg_output_is_refused(tmp_path: Path) -> None:
    source = load_source(_master(tmp_path))
    saved = save_edit(source, _recipe(source), cancel=Event())
    jpg = saved.image.with_suffix(".jpg")
    jpg.write_bytes(saved.image.read_bytes())
    payload = json.loads(saved.sidecar.read_bytes())
    payload["output"] = {"name": jpg.name, "sha256": hashlib.sha256(jpg.read_bytes()).hexdigest()}
    saved.sidecar.write_bytes(json.dumps(payload).encode())
    with pytest.raises(PhotoEditError, match="formats do not match"):
        open_edit(saved.sidecar)


def test_a_jpeg_source_with_a_png_output_name_is_refused(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    saved = save_edit(source, _recipe(source), cancel=Event())
    png = saved.image.with_suffix(".png")
    png.write_bytes(saved.image.read_bytes())
    payload = json.loads(saved.sidecar.read_bytes())
    payload["output"] = {"name": png.name, "sha256": hashlib.sha256(png.read_bytes()).hexdigest()}
    saved.sidecar.write_bytes(json.dumps(payload).encode())
    with pytest.raises(PhotoEditError, match="formats do not match"):
        open_edit(saved.sidecar)


def _big_description_master(tmp_path: Path, size: int = 65_450) -> Path:
    exif = Image.Exif()
    exif[270] = "a" * size
    tiff = exif.tobytes()[6:]
    assert len(tiff) <= 65_533
    path = tmp_path / "photo_0001.png"
    path.write_bytes(h.replace_kind(h.master_png(), b"eXIf", (b"eXIf", tiff)))
    return path


def test_metadata_that_grows_past_the_input_limit_is_refused_on_save(tmp_path: Path) -> None:
    source = load_source(_big_description_master(tmp_path))
    with pytest.raises(PhotoEditError, match="metadata is too large"):
        save_edit(source, _recipe(source), cancel=Event())
    assert not list(tmp_path.glob("*_edit-*"))


def test_xmp_that_grows_past_the_input_limit_is_refused_on_save(tmp_path: Path) -> None:
    base = load_source(_master(tmp_path))
    huge = replace(
        base, xmp=b'<x:xmpmeta xmlns:x="adobe:ns:meta/">' + b" " * 65_600 + b"</x:xmpmeta>"
    )
    with pytest.raises(PhotoEditError, match="metadata is too large"):
        save_edit(huge, _recipe(huge), cancel=Event())


def test_a_jpeg_save_refuses_oversized_metadata_the_same_way(tmp_path: Path) -> None:
    base = source_at(tmp_path)
    exif = Image.Exif()
    exif[270] = "a" * 65_450
    huge = replace(base, exif=exif.tobytes())
    with pytest.raises(PhotoEditError, match="metadata is too large"):
        save_edit(huge, _recipe(huge), cancel=Event())


@pytest.mark.parametrize("error", [TypeError, struct.error, AttributeError, KeyError, IndexError])
def test_a_save_with_unwritable_exif_raises_photo_edit_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: type[Exception]
) -> None:
    source = load_source(_master(tmp_path))

    def broken(*_args: object) -> bytes:
        raise error("bad tag")

    monkeypatch.setattr("fastfoto_linux.photo_edits.store.derivative_exif", broken)
    with pytest.raises(PhotoEditError, match="cannot be rewritten"):
        save_edit(source, _recipe(source), cancel=Event())


def test_600_dpi_survives_two_generations_exactly(tmp_path: Path) -> None:
    source = load_source(_master(tmp_path))
    first = save_edit(source, _recipe(source), cancel=Event())
    reopened, recipe = open_edit(first.sidecar)
    assert reopened.effective_dpi == 600
    second = save_edit(reopened, recipe, cancel=Event())
    edit = load_source(second.image)
    assert (edit.dpi_x, edit.dpi_y) == (600, 600)
    third = save_edit(edit, _recipe(edit), cancel=Event())
    assert load_source(third.image).effective_dpi == 600


def _xmp_packet(size: int) -> bytes:
    head, tail = b'<x:xmpmeta xmlns:x="adobe:ns:meta/">', b"</x:xmpmeta>"
    return head + b" " * (size - len(head) - len(tail)) + tail


def test_the_largest_accepted_xmp_survives_save_and_reopen(tmp_path: Path) -> None:
    path = tmp_path / "Album_0001.png"
    packet = _xmp_packet(MAX_XMP_PACKET)
    path.write_bytes(h.replace_kind(h.master_png(), b"iTXt", h.itxt_xmp(packet, compressed=True)))
    source = load_source(path)
    assert source.xmp == packet
    saved = save_edit(source, _recipe(source), cancel=Event())
    assert load_source(saved.image).xmp == packet


def test_an_xmp_one_byte_past_the_packet_limit_is_refused_on_load(tmp_path: Path) -> None:
    path = tmp_path / "Album_0001.png"
    packet = _xmp_packet(MAX_XMP_PACKET + 1)
    path.write_bytes(h.replace_kind(h.master_png(), b"iTXt", h.itxt_xmp(packet, compressed=True)))
    with pytest.raises(PhotoEditError, match="metadata"):
        load_source(path)


def test_a_png_save_refuses_xmp_whose_chunk_would_not_reopen(tmp_path: Path) -> None:
    base = load_source(_master(tmp_path))
    huge = replace(base, xmp=_xmp_packet(MAX_XMP_PACKET + 1))
    with pytest.raises(PhotoEditError, match="metadata is too large"):
        save_edit(huge, _recipe(huge), cancel=Event())


@pytest.mark.parametrize("kind", ["png", "jpeg"])
def test_a_dpi_the_file_format_cannot_store_is_refused_on_save(tmp_path: Path, kind: str) -> None:
    base = load_source(_master(tmp_path)) if kind == "png" else source_at(tmp_path)
    huge = replace(base, dpi_x=200_000_000.0, dpi_y=200_000_000.0, effective_dpi=200_000_000.0)
    with pytest.raises(PhotoEditError, match="resolution"):
        save_edit(huge, _recipe(huge), cancel=Event())
