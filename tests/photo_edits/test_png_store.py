"""PNG in, PNG out: the edit keeps the master's format, metadata and 600 dpi."""

from pathlib import Path
from threading import Event

import numpy as np
from PIL import Image

from fastfoto_linux.photo_edits import load_source, open_edit, recipe_bytes, save_edit
from fastfoto_linux.photo_edits.model import PhotoEditRecipe
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
