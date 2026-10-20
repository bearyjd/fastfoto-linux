"""Straighten through render, preview, save/reopen and metadata."""

import importlib
from dataclasses import replace
from pathlib import Path
from threading import Event

import numpy as np
import pytest
from PIL import ExifTags, Image

from fastfoto_linux.photo_edits import (
    PhotoEditCancelledError,
    PhotoEditError,
    PhotoEditRecipe,
    PhotoGeometry,
    apply_geometry,
    load_source,
    make_preview,
    manual_eye,
    open_edit,
    output_size,
    recipe_bytes,
    render,
    save_edit,
)
from fastfoto_linux.photo_edits import straighten as st
from fastfoto_linux.photo_edits.metadata import derivative_exif
from tests.photo_edits.helpers import eye, pixels, source_at
from tests.photo_edits.straighten_helpers import TONE, sized_source, straight_recipe

renderer = importlib.import_module("fastfoto_linux.photo_edits.render")
RED = (230, 20, 20)


def jpeg(array: np.ndarray, source, *, bounded: bool = True) -> bytes:
    return renderer._preview_jpeg(array, bounded=bounded, icc_profile=source.icc_profile)[0]


def corner_eye_source(tmp_path: Path):
    source = source_at(tmp_path)
    painted = source.pixels.copy()
    painted[0:14, 0:14] = RED
    return replace(source, pixels=painted)


def corner_eye(source, eye_id: str = "corner"):
    return manual_eye(source, eye_id=eye_id, cx=6, cy=6, rx=4, ry=4)


def test_render_is_eyes_then_straighten_crop_turn_then_tone(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    recipe = straight_recipe(source, PhotoGeometry(1, (3, 4, 100, 70), 37), eyes=(eye(),))
    eyes_only = render(
        source, replace(recipe, geometry=PhotoGeometry(), tone=recipe.tone), cancel=Event()
    )
    expected = apply_geometry(eyes_only, recipe.geometry)
    assert np.array_equal(render(source, recipe, cancel=Event()), expected)


def test_straighten_commutes_with_per_pixel_tone_only_up_to_the_definition(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    recipe = straight_recipe(source, PhotoGeometry(2, None, -60), tone=TONE)
    plain = replace(recipe, tone=type(recipe.tone)())
    result = render(source, recipe, cancel=Event())
    warped = render(source, plain, cancel=Event())
    assert result.shape == warped.shape and not np.array_equal(result, warped)


def test_an_eye_outside_the_frame_has_no_effect_but_still_checks_overlap(tmp_path: Path) -> None:
    source = corner_eye_source(tmp_path)
    geometry = PhotoGeometry(0, None, 150)
    with_eye = straight_recipe(source, geometry, eyes=(corner_eye(source),))
    without = straight_recipe(source, geometry)
    assert np.array_equal(
        render(source, with_eye, cancel=Event()), render(source, without, cancel=Event())
    )
    flat = straight_recipe(source, PhotoGeometry(), eyes=(corner_eye(source),))
    assert not np.array_equal(
        render(source, flat, cancel=Event()),
        render(source, PhotoEditRecipe(source), cancel=Event()),
    )
    twin = straight_recipe(
        source, geometry, eyes=(corner_eye(source, "a"), corner_eye(source, "b"))
    )
    with pytest.raises(PhotoEditError, match="overlap"):
        render(source, twin, cancel=Event())


def test_cancellation_is_raised_between_warp_tiles_before_any_tone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = sized_source(tmp_path, 700, 1100)
    recipe = straight_recipe(source, PhotoGeometry(0, None, 100), tone=TONE)
    cancel, calls, tones = Event(), [], []
    real = st.warp_tile

    def watched(*args):
        calls.append(1)
        cancel.set()
        return real(*args)

    monkeypatch.setattr(st, "warp_tile", watched)
    monkeypatch.setattr(renderer, "_tone_tile", lambda *a: tones.append(1))
    with pytest.raises(PhotoEditCancelledError):
        render(source, recipe, cancel=cancel)
    assert len(calls) == 1 and not tones


def test_cancellation_before_the_first_tile_never_warps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = sized_source(tmp_path, 300, 400)
    recipe = straight_recipe(source, PhotoGeometry(0, None, 100))
    cancel = Event()
    cancel.set()
    monkeypatch.setattr(st, "warp_tile", lambda *a: pytest.fail("warped after cancel"))
    with pytest.raises(PhotoEditCancelledError):
        apply_geometry(source.pixels, recipe.geometry, cancel=cancel)


def test_apply_geometry_without_cancel_still_works_and_neutral_ignores_it(tmp_path: Path) -> None:
    array = pixels()
    fired = Event()
    fired.set()
    assert np.array_equal(apply_geometry(array, PhotoGeometry(), cancel=fired), array)
    assert apply_geometry(array, PhotoGeometry(0, None, 5)).shape[2] == 3


def test_preview_after_equals_the_bounded_render_and_straightened_is_last(tmp_path: Path) -> None:
    source = sized_source(tmp_path, 1000, 1800)
    recipe = straight_recipe(source, PhotoGeometry(1, None, 23), tone=TONE)
    preview = make_preview(source, recipe, cache_dir=tmp_path / "c", generation=3, cancel=Event())
    full = render(source, recipe, cancel=Event())
    assert preview.after.read_bytes() == jpeg(full, source)
    thumb = Image.new("RGB", output_size(source, recipe.geometry))
    thumb.thumbnail((1600, 1600))
    assert (preview.preview_width, preview.preview_height) == thumb.size
    assert preview.straightened is not None and preview.straightened.name.endswith("-3.jpg")
    working = render(source, replace(recipe, geometry=PhotoGeometry()), cancel=Event())
    flat = apply_geometry(working, PhotoGeometry(0, None, 23))
    assert preview.straightened.read_bytes() == jpeg(flat, source)
    assert preview.working.read_bytes() == jpeg(working, source)
    assert preview.before.read_bytes() == jpeg(source.pixels, source)


def test_straightened_is_absent_at_zero_and_after_the_roi_pair(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    flat = straight_recipe(source, PhotoGeometry(1), eyes=(eye(),))
    assert (
        make_preview(
            source, flat, cache_dir=tmp_path / "a", generation=1, cancel=Event(), selected_id="left"
        ).straightened
        is None
    )
    angled = straight_recipe(source, PhotoGeometry(0, None, -40), eyes=(eye(),))
    preview = make_preview(
        source, angled, cache_dir=tmp_path / "b", generation=1, cancel=Event(), selected_id="left"
    )
    assert preview.straightened.name.endswith("-5.jpg")
    assert preview.roi_before.name.endswith("-3.jpg") and preview.roi_after.name.endswith("-4.jpg")
    x0, y0, x1, y1 = angled.eyes[0].roi
    working = render(source, replace(angled, geometry=PhotoGeometry()), cancel=Event())
    assert preview.roi_before.read_bytes() == jpeg(
        source.pixels[y0:y1, x0:x1], source, bounded=False
    )
    assert preview.roi_after.read_bytes() == jpeg(working[y0:y1, x0:x1], source, bounded=False)


def test_zero_angle_preview_matches_the_previous_blob_layout(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    recipe = straight_recipe(source, PhotoGeometry(1, (10, 5, 100, 80)))
    preview = make_preview(source, recipe, cache_dir=tmp_path / "z", generation=1, cancel=Event())
    assert preview.straightened is None and preview.roi_before is None
    assert [preview.before.name[-5], preview.after.name[-5], preview.working.name[-5]] == list(
        "012"
    )


def test_preview_cancellation_during_the_warp(tmp_path: Path, monkeypatch) -> None:
    source = sized_source(tmp_path, 700, 1100)
    recipe = straight_recipe(source, PhotoGeometry(0, None, 100))
    cancel, real = Event(), st.warp_tile

    def watched(*args):
        cancel.set()
        return real(*args)

    monkeypatch.setattr(st, "warp_tile", watched)
    with pytest.raises(PhotoEditCancelledError):
        make_preview(source, recipe, cache_dir=tmp_path / "c", generation=1, cancel=cancel)
    assert not (tmp_path / "c").exists() or not list((tmp_path / "c").iterdir())


def test_save_and_reopen_replays_from_the_source(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    recipe = straight_recipe(
        source, PhotoGeometry(3, (4, 4, 120, 70), -45), tone=TONE, eyes=(eye(),)
    )
    saved = save_edit(source, recipe, cancel=Event())
    reopened_source, reopened = open_edit(saved.sidecar)
    assert (reopened.geometry, reopened.tone) == (recipe.geometry, recipe.tone)
    assert (reopened.schema_version, reopened.eyes[0].id) == (4, "left")
    assert recipe_bytes(open_edit(saved.sidecar)[1]) == recipe_bytes(reopened)
    assert np.array_equal(
        render(reopened_source, reopened, cancel=Event()), render(source, recipe, cancel=Event())
    )
    assert Image.open(saved.image).size == output_size(source, recipe.geometry)


def _dimension_source(tmp_path: Path):
    exif = Image.Exif()
    exif[ExifTags.Base.Orientation] = 1
    exif[ExifTags.Base.XResolution] = 300
    exif[ExifTags.Base.YResolution] = 300
    exif[ExifTags.Base.ResolutionUnit] = 2
    exif[256], exif[257] = 160, 100
    exif.get_ifd(ExifTags.IFD.Exif)[40962] = 160
    exif.get_ifd(ExifTags.IFD.Exif)[40963] = 100
    path = tmp_path / "photo.jpg"
    Image.fromarray(pixels()).save(path, exif=exif, dpi=(300, 300))
    return load_source(path)


def test_metadata_takes_the_straightened_output_size(tmp_path: Path) -> None:
    source = _dimension_source(tmp_path)
    geometry = PhotoGeometry(1, None, 37)
    width, height = output_size(source, geometry)
    fw, fh = st.straightened_size(160, 100, 37)
    assert (width, height) == (fh, fw)
    exif = Image.Exif()
    exif.load(derivative_exif(source, geometry))
    assert (exif[256], exif[257]) == (width, height)
    details = exif.get_ifd(ExifTags.IFD.Exif)
    assert (details[40962], details[40963]) == (width, height)
    assert exif[ExifTags.Base.Orientation] == 1
    assert (float(exif[ExifTags.Base.XResolution]), float(exif[ExifTags.Base.YResolution])) == (
        300,
        300,
    )
    saved = save_edit(source, straight_recipe(source, geometry), cancel=Event())
    with Image.open(saved.image) as image:
        assert image.size == (width, height) and image.info["dpi"] == (300, 300)
        assert image.getexif()[ExifTags.Base.Orientation] == 1


def test_output_size_swaps_on_odd_turns_with_a_straightened_crop(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    fw, fh = st.straightened_size(160, 100, 37)
    assert output_size(source, PhotoGeometry(0, None, 37)) == (fw, fh)
    assert output_size(source, PhotoGeometry(3, None, 37)) == (fh, fw)
    assert output_size(source, PhotoGeometry(1, (2, 3, 50, 40), 37)) == (37, 48)
