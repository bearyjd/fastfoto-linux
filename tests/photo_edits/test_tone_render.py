"""Photo-tone-v1 golden arithmetic, eye composition and bounded cancellable tiles."""

import importlib
from dataclasses import replace
from pathlib import Path
from threading import Event

import numpy as np
import pytest

from fastfoto_linux.photo_edits import (
    PhotoEditCancelledError,
    PhotoEditRecipe,
    PhotoTone,
    make_preview,
    render,
    save_edit,
)
from tests.photo_edits.helpers import eye, source_at
from tests.photo_edits.tone_helpers import reference_tone, tone_source

renderer = importlib.import_module("fastfoto_linux.photo_edits.render")
TILE_LIMIT = 262_144


@pytest.mark.parametrize(
    "pixel,tone,expected",
    [
        ((255, 0, 0), PhotoTone(saturation=-100), (54, 54, 54)),
        ((0, 0, 0), PhotoTone(brightness=50), (64, 64, 64)),
        ((45, 45, 45), PhotoTone(brightness=-20), (20, 20, 20)),
        (
            (255, 0, 0),
            PhotoTone(brightness=50, contrast=50, saturation=-100, strength=50),
            (184, 57, 57),
        ),
        ((255, 10, 0), PhotoTone(contrast=50, saturation=100, strength=50), (255, 0, 0)),
        (
            (0, 255, 128),
            PhotoTone(brightness=-50, contrast=-50, saturation=100, strength=37),
            (0, 231, 104),
        ),
    ],
)
def test_fixed_formula_goldens(
    tmp_path: Path, pixel: tuple, tone: PhotoTone, expected: tuple
) -> None:
    source = tone_source(tmp_path, np.array([[pixel]], dtype=np.uint8))
    actual = render(source, PhotoEditRecipe(source, tone=tone), cancel=Event())
    assert actual.dtype == np.uint8
    assert actual[0, 0].tolist() == list(expected)


@pytest.mark.parametrize("strength", [0, 1, 37, 100])
def test_neutral_controls_preserve_every_channel_exactly(tmp_path: Path, strength: int) -> None:
    ramp = np.arange(256, dtype=np.uint8)
    pixels = np.stack((ramp, ramp[::-1], np.roll(ramp, 91)), axis=-1)[None]
    source = tone_source(tmp_path, pixels)
    tone = PhotoTone(strength=strength)
    actual = render(source, PhotoEditRecipe(source, tone=tone), cancel=Event())
    assert np.array_equal(actual, pixels)
    assert actual is not source.pixels


def test_strength_zero_keeps_accepted_eye_render_byte_identical(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    legacy = PhotoEditRecipe(source, (eye(),), 1, "redeye-v1")
    baseline = render(source, legacy, cancel=Event())
    recipe = PhotoEditRecipe(
        source, legacy.eyes, tone=PhotoTone(brightness=50, contrast=-50, saturation=100, strength=0)
    )
    assert np.array_equal(render(source, recipe, cancel=Event()), baseline)
    assert not np.array_equal(baseline, source.pixels)


@pytest.mark.parametrize("shape", [(1, 1), (3, 7), (17, 19)])
@pytest.mark.parametrize(
    "tone",
    [PhotoTone(50, 50, 100, 100), PhotoTone(-50, -50, -100, 100), PhotoTone(13, -27, 69, 41)],
)
def test_odd_rgb_patterns_match_independent_scalar_formula(
    tmp_path: Path, shape: tuple[int, int], tone: PhotoTone
) -> None:
    pixels = np.random.default_rng(51).integers(0, 256, (*shape, 3), dtype=np.uint8)
    source = tone_source(tmp_path, pixels)
    recipe = PhotoEditRecipe(source, tone=tone)
    expected = reference_tone(pixels, tone)
    first = render(source, recipe, cancel=Event())
    assert np.array_equal(first, expected)
    assert np.array_equal(first, render(source, recipe, cancel=Event()))
    assert np.array_equal(source.pixels, pixels)


def test_eyes_run_before_tone_and_source_masks_and_recipe_stay_immutable(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    edits = (eye(), eye("right", accepted=False, right=True))
    pixels_before, mask_before = source.pixels.copy(), edits[0].mask.copy()
    legacy = PhotoEditRecipe(source, edits, 1, "redeye-v1")
    corrected = render(source, legacy, cancel=Event())
    tone = PhotoTone(20, -35, 55, 60)
    recipe = PhotoEditRecipe(source, edits, tone=tone)
    neutral = PhotoEditRecipe(source, edits)
    assert np.array_equal(render(source, neutral, cancel=Event()), corrected)
    assert np.array_equal(render(source, recipe, cancel=Event()), reference_tone(corrected, tone))
    assert np.array_equal(source.pixels, pixels_before)
    assert np.array_equal(edits[0].mask, mask_before)
    assert not source.pixels.flags.writeable and not edits[0].mask.flags.writeable
    assert recipe.eyes is edits and recipe.tone == tone and not edits[1].accepted
    assert np.array_equal(
        render(source, replace(recipe, tone=PhotoTone()), cancel=Event()), corrected
    )


def test_tiles_are_bounded_contiguous_and_boundary_independent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pixel = np.array([[[37, 149, 231]]], dtype=np.uint8)
    source = tone_source(tmp_path, np.tile(pixel, (1025, 257, 1)))
    tone = PhotoTone(21, -18, 77, 63)
    recipe = PhotoEditRecipe(source, tone=tone)
    calls = []
    original = renderer._tone_tile

    def record_tile(pixels: np.ndarray, controls: PhotoTone) -> np.ndarray:
        assert pixels.flags.c_contiguous
        assert pixels.size // 3 <= TILE_LIMIT
        calls.append(pixels.size // 3)
        return original(pixels, controls)

    monkeypatch.setattr(renderer, "_tone_tile", record_tile)
    first = render(source, recipe, cancel=Event())
    assert sum(calls) == source.width * source.height
    assert len(calls) >= 2 and max(calls) <= TILE_LIMIT
    assert np.array_equal(first, np.tile(reference_tone(pixel, tone), (1025, 257, 1)))
    calls.clear()
    monkeypatch.setattr(renderer, "TONE_TILE_PIXELS", 4093)
    second = render(source, recipe, cancel=Event())
    assert calls and max(calls) <= 4093
    assert np.array_equal(first, second)


@pytest.mark.parametrize("operation", ["render", "preview", "save"])
@pytest.mark.parametrize("tile_size", [500, TILE_LIMIT])
def test_cancel_after_tone_tile_stops_work_and_publishes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str, tile_size: int
) -> None:
    source = source_at(tmp_path)
    original_bytes = source.path.read_bytes()
    pixels_before = source.pixels.copy()
    recipe = PhotoEditRecipe(source, tone=PhotoTone(brightness=30))
    cancel = Event()
    calls = []
    original = renderer._tone_tile

    def cancel_after_tile(pixels: np.ndarray, tone: PhotoTone) -> np.ndarray:
        calls.append(pixels.shape)
        output = original(pixels, tone)
        cancel.set()
        return output

    monkeypatch.setattr(renderer, "TONE_TILE_PIXELS", tile_size)
    monkeypatch.setattr(renderer, "_tone_tile", cancel_after_tile)
    with pytest.raises(PhotoEditCancelledError):
        if operation == "render":
            render(source, recipe, cancel=cancel)
        elif operation == "preview":
            make_preview(source, recipe, cache_dir=tmp_path / "cache", generation=1, cancel=cancel)
        else:
            save_edit(source, recipe, cancel=cancel)
    assert len(calls) == 1
    assert not (tmp_path / "cache").exists()
    assert not list(tmp_path.glob("*_edit-*"))
    assert source.path.read_bytes() == original_bytes
    assert np.array_equal(source.pixels, pixels_before)
