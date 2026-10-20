"""Exact pixel contract: eyes, then crop, then clockwise turns, then tone."""

import importlib
import json
from dataclasses import replace
from pathlib import Path
from threading import Event

import numpy as np
import pytest
from PIL import Image

from fastfoto_linux.photo_edits import (
    PhotoEditCancelledError,
    PhotoEditError,
    PhotoGeometry,
    PhotoTone,
    apply_geometry,
    make_preview,
    open_edit,
    output_size,
    render,
    save_edit,
    update_geometry,
)
from tests.photo_edits.geometry_helpers import GRID_RGB, TONE, geometry_recipe
from tests.photo_edits.helpers import eye, source_at
from tests.photo_edits.tone_helpers import tone_source

renderer = importlib.import_module("fastfoto_linux.photo_edits.render")
store = importlib.import_module("fastfoto_linux.photo_edits.store")
CROP = (10, 5, 100, 80)


@pytest.mark.parametrize(
    ("turns", "expected"),
    [
        (1, [[4, 1], [5, 2], [6, 3]]),
        (2, [[6, 5, 4], [3, 2, 1]]),
        (3, [[3, 6], [2, 5], [1, 4]]),
    ],
)
def test_clockwise_quarter_turns_of_a_literal_array(turns: int, expected: list) -> None:
    result = apply_geometry(GRID_RGB, PhotoGeometry(turns))
    base = np.array(expected, dtype=np.uint8)
    assert np.array_equal(result, np.stack([base, base + 10, base + 20], axis=-1))


def test_neutral_geometry_returns_equal_pixels() -> None:
    assert np.array_equal(apply_geometry(GRID_RGB, PhotoGeometry()), GRID_RGB)


def test_crops_are_exact_half_open_slices() -> None:
    array = np.arange(4 * 5 * 3, dtype=np.uint8).reshape(4, 5, 3)
    for crop in ((1, 1, 4, 3), (0, 0, 5, 1), (4, 3, 5, 4), (0, 0, 1, 4)):
        left, top, right, bottom = crop
        result = apply_geometry(array, PhotoGeometry(0, crop))
        assert np.array_equal(result, array[top:bottom, left:right])


def test_crop_happens_before_the_turn() -> None:
    array = np.arange(4 * 5 * 3, dtype=np.uint8).reshape(4, 5, 3)
    result = apply_geometry(array, PhotoGeometry(1, (1, 0, 4, 2)))
    cropped = array[0:2, 1:4]
    assert result.shape == (3, 2, 3)
    assert np.array_equal(result[0, 0], cropped[1, 0]) and np.array_equal(
        result[0, 1], cropped[0, 0]
    )


@pytest.mark.parametrize("turns", [0, 1, 2, 3])
@pytest.mark.parametrize("crop", [None, (1, 1, 4, 3)])
def test_output_is_a_fresh_contiguous_array_and_input_is_untouched(
    turns: int, crop: tuple | None
) -> None:
    array = np.arange(4 * 5 * 3, dtype=np.uint8).reshape(4, 5, 3)
    before = array.copy()
    result = apply_geometry(array, PhotoGeometry(turns, crop))
    assert result.flags["C_CONTIGUOUS"] and result.dtype == np.uint8
    assert not np.shares_memory(result, array)
    assert np.array_equal(array, before)
    result[...] = 0
    assert np.array_equal(array, before)


def test_output_size_swaps_axes_on_odd_turns(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    assert output_size(source, PhotoGeometry()) == (160, 100)
    assert output_size(source, PhotoGeometry(1)) == (100, 160)
    assert output_size(source, PhotoGeometry(2)) == (160, 100)
    assert output_size(source, PhotoGeometry(3)) == (100, 160)
    assert output_size(source, PhotoGeometry(0, CROP)) == (90, 75)
    assert output_size(source, PhotoGeometry(1, CROP)) == (75, 90)


def test_render_orders_eyes_then_crop_then_turn_then_tone(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    geometry = PhotoGeometry(1, CROP)
    plain = geometry_recipe(source, PhotoGeometry(), eyes=(eye(right=True),), tone=TONE)
    full = render(source, plain, cancel=Event())
    recipe = geometry_recipe(source, geometry, eyes=(eye(right=True),), tone=TONE)
    result = render(source, recipe, cancel=Event())
    assert np.array_equal(result, apply_geometry(full, geometry))
    untoned = geometry_recipe(source, geometry, eyes=(eye(right=True),))
    assert not np.array_equal(result, render(source, untoned, cancel=Event()))
    assert result.flags["C_CONTIGUOUS"]


def test_tone_writes_through_a_turned_crop_not_a_copy(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    toned = geometry_recipe(source, PhotoGeometry(3, CROP), tone=PhotoTone(brightness=40))
    plain = geometry_recipe(source, PhotoGeometry(3, CROP))
    assert not np.array_equal(
        render(source, toned, cancel=Event()), render(source, plain, cancel=Event())
    )


def test_render_never_mutates_the_source(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    before = source.pixels.copy()
    render(source, geometry_recipe(source, PhotoGeometry(1, CROP), tone=TONE), cancel=Event())
    assert np.array_equal(source.pixels, before)
    result = render(source, geometry_recipe(source, PhotoGeometry(2)), cancel=Event())
    assert not np.shares_memory(result, source.pixels)


def test_eye_outside_the_crop_has_no_effect(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    geometry = PhotoGeometry(0, (80, 0, 160, 100))
    with_eye = geometry_recipe(source, geometry, eyes=(eye(),))
    without = geometry_recipe(source, geometry)
    result = render(source, with_eye, cancel=Event())
    assert np.array_equal(result, render(source, without, cancel=Event()))
    assert np.array_equal(result, source.pixels[0:100, 80:160])


def test_eye_inside_the_crop_is_applied_in_source_space(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    geometry = PhotoGeometry(0, (60, 0, 160, 100))
    result = render(
        source, geometry_recipe(source, geometry, eyes=(eye(right=True),)), cancel=Event()
    )
    assert not np.array_equal(result, source.pixels[0:100, 60:160])


def test_overlapping_accepted_eyes_still_raise_when_outside_the_crop(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    recipe = geometry_recipe(source, PhotoGeometry(0, (80, 0, 160, 100)), eyes=(eye("a"), eye("b")))
    with pytest.raises(PhotoEditError, match="overlap"):
        render(source, recipe, cancel=Event())


def test_render_rejects_a_recipe_for_another_source_even_if_cropped(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    recipe = geometry_recipe(source, PhotoGeometry(1, CROP))
    other = replace(source, sha256="0" * 64)
    with pytest.raises(PhotoEditError, match="identity"):
        render(other, recipe, cancel=Event())


def test_cancellation_is_checked_before_geometry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = source_at(tmp_path)
    recipe = geometry_recipe(source, PhotoGeometry(1, CROP), eyes=(eye(),), tone=TONE)
    cancel = Event()
    real = renderer.redeye.apply_fixes

    def cancelling(*args: object, **kwargs: object) -> np.ndarray:
        cancel.set()
        return real(*args, **kwargs)

    called: list[bool] = []
    monkeypatch.setattr(renderer.redeye, "apply_fixes", cancelling)
    monkeypatch.setattr(renderer, "apply_geometry", lambda *a, **k: called.append(True))
    with pytest.raises(PhotoEditCancelledError):
        render(source, recipe, cancel=cancel)
    assert called == []


def test_cancellation_between_tone_tiles_after_geometry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = source_at(tmp_path)
    recipe = geometry_recipe(source, PhotoGeometry(1, CROP), tone=TONE)
    cancel = Event()
    real = renderer.apply_geometry

    def cancelling(*args: object, **kwargs: object) -> np.ndarray:
        result = real(*args, **kwargs)
        cancel.set()
        return result

    tiles: list[bool] = []
    monkeypatch.setattr(renderer, "apply_geometry", cancelling)
    monkeypatch.setattr(renderer, "_tone_tile", lambda *a, **k: tiles.append(True))
    with pytest.raises(PhotoEditCancelledError):
        render(source, recipe, cancel=cancel)
    assert tiles == []


def test_cancellation_after_geometry_with_neutral_tone_is_final_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = source_at(tmp_path)
    recipe = geometry_recipe(source, PhotoGeometry(2))
    cancel = Event()
    real = renderer.apply_geometry
    monkeypatch.setattr(
        renderer, "apply_geometry", lambda *a, **k: (cancel.set(), real(*a, **k))[1]
    )
    with pytest.raises(PhotoEditCancelledError):
        render(source, recipe, cancel=cancel)


def test_cancellation_before_publish_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = source_at(tmp_path)
    recipe = geometry_recipe(source, PhotoGeometry(1, CROP))
    cancel = Event()
    real = store.render
    monkeypatch.setattr(store, "render", lambda *a, **k: (cancel.set(), real(*a, **k))[1])
    with pytest.raises(PhotoEditCancelledError):
        save_edit(source, recipe, cancel=cancel)
    assert sorted(path.name for path in tmp_path.iterdir()) == ["photo_0001.jpg"]


def test_neutral_v3_saves_the_same_bytes_as_v2(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    source_a, source_b = source_at(tmp_path / "a"), source_at(tmp_path / "b")
    v2 = geometry_recipe(source_a, PhotoGeometry(), eyes=(eye(),), tone=TONE)
    v3 = update_geometry(
        geometry_recipe(source_b, PhotoGeometry(1, CROP), eyes=(eye(),), tone=TONE), PhotoGeometry()
    )
    assert (v2.schema_version, v3.schema_version) == (2, 3)
    saved_a = save_edit(source_a, v2, cancel=Event())
    saved_b = save_edit(source_b, v3, cancel=Event())
    assert saved_a.image.read_bytes() == saved_b.image.read_bytes()


def test_save_and_reopen_replays_geometry_from_the_source(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    recipe = geometry_recipe(source, PhotoGeometry(3, CROP), eyes=(eye(right=True),), tone=TONE)
    saved = save_edit(source, recipe, cancel=Event())
    with Image.open(saved.image) as derivative:
        assert derivative.size == output_size(source, recipe.geometry) == (75, 90)
    reopened_source, reopened = open_edit(saved.sidecar)
    assert reopened.geometry == recipe.geometry and reopened.schema_version == 3
    assert np.array_equal(
        render(reopened_source, reopened, cancel=Event()), render(source, recipe, cancel=Event())
    )
    again = save_edit(reopened_source, reopened, cancel=Event())
    assert again.image.read_bytes() == saved.image.read_bytes()
    first, second = (json.loads(path.sidecar.read_bytes()) for path in (saved, again))
    assert first.pop("output")["sha256"] == second.pop("output")["sha256"]
    assert first == second


def _jpeg(pixels: np.ndarray, *, bounded: bool = True) -> bytes:
    return renderer._preview_jpeg(pixels, bounded=bounded, icc_profile=None)[0]


def test_preview_has_working_after_and_pre_geometry_eye_crops(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    geometry = PhotoGeometry(1, CROP)
    recipe = geometry_recipe(source, geometry, eyes=(eye(right=True),), tone=TONE)
    neutral = geometry_recipe(source, PhotoGeometry(), eyes=(eye(right=True),), tone=TONE)
    preview = make_preview(
        source,
        recipe,
        cache_dir=tmp_path / "cache",
        generation=1,
        cancel=Event(),
        selected_id="left",
    )
    old = make_preview(
        source,
        neutral,
        cache_dir=tmp_path / "old",
        generation=1,
        cancel=Event(),
        selected_id="left",
    )
    assert preview.working is not None and preview.roi_before and preview.roi_after
    assert (preview.source_width, preview.source_height) == (160, 100)
    assert preview.working.read_bytes() == old.after.read_bytes()
    assert preview.before.read_bytes() == old.before.read_bytes() == _jpeg(source.pixels)
    with Image.open(preview.after) as after:
        assert after.size == output_size(source, geometry) == (75, 90)
        assert (preview.preview_width, preview.preview_height) == after.size
    full = render(source, neutral, cancel=Event())
    assert preview.after.read_bytes() == _jpeg(apply_geometry(full, geometry))
    assert preview.after.read_bytes() != old.after.read_bytes()
    x0, y0, x1, y1 = recipe.eyes[0].roi
    assert preview.roi_before.read_bytes() == _jpeg(source.pixels[y0:y1, x0:x1], bounded=False)
    assert preview.roi_after.read_bytes() == _jpeg(full[y0:y1, x0:x1], bounded=False)
    names = [p.name for p in (preview.before, preview.after, preview.working)]
    assert [n.rsplit("-", 1)[1] for n in names] == ["0.jpg", "1.jpg", "2.jpg"]
    assert preview.roi_before.name.endswith("-3.jpg") and preview.roi_after.name.endswith("-4.jpg")


def test_neutral_preview_working_equals_after_and_has_no_crops(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    recipe = geometry_recipe(source, PhotoGeometry(), eyes=(eye(),), tone=TONE)
    preview = make_preview(source, recipe, cache_dir=tmp_path / "c", generation=0, cancel=Event())
    assert preview.working is not None
    assert preview.working.read_bytes() == preview.after.read_bytes()
    assert preview.roi_before is None and preview.roi_after is None


def test_preview_size_is_the_bounded_output_not_the_source(tmp_path: Path) -> None:
    source = tone_source(tmp_path, np.zeros((900, 1800, 3), dtype=np.uint8))
    recipe = geometry_recipe(source, PhotoGeometry(1))
    preview = make_preview(source, recipe, cache_dir=tmp_path / "c", generation=0, cancel=Event())
    assert (preview.preview_width, preview.preview_height) == (800, 1600)
    with Image.open(preview.before) as before, Image.open(preview.after) as after:
        assert before.size == (1600, 800) and after.size == (800, 1600)


def test_preview_cancellation_leaves_no_files(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    cancel = Event()
    cancel.set()
    with pytest.raises(PhotoEditCancelledError):
        make_preview(
            source,
            geometry_recipe(source, PhotoGeometry(1)),
            cache_dir=tmp_path / "c",
            generation=0,
            cancel=cancel,
        )
    assert not (tmp_path / "c").exists() or not list((tmp_path / "c").iterdir())
