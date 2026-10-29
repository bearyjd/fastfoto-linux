"""White-balance LUT goldens, bypass, render order, tiles, cancellation and previews."""

import json
from dataclasses import replace
from pathlib import Path
from threading import Event

import numpy as np
import pytest

from fastfoto_linux.photo_edits import (
    PhotoEditCancelledError,
    PhotoEditRecipe,
    PhotoGeometry,
    PhotoTone,
    PhotoWhiteBalance,
    color,
    make_preview,
    parse_recipe,
    recipe_bytes,
    render,
    update_geometry,
    update_tone,
    update_white_balance,
)
from tests.photo_edits.helpers import eye, source_at
from tests.photo_edits.straighten_helpers import TONE, noise, straight_recipe
from tests.photo_edits.tone_helpers import reference_tone, tone_source
from tests.photo_edits.wb_helpers import (
    GOLDEN_PAIRS,
    gains,
    luminance,
    reference_lut,
    reference_wb,
)

WB = PhotoWhiteBalance(100, 0)


def _boom(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("the neutral path must not build a LUT")


def test_gain_spot_values() -> None:
    expected = {
        (100, 0): (1.3255, 0.9373, 0.6628),
        (0, 100): (1.2650, 0.8945, 1.2650),
        (25, 0): (1.0762, 0.9869, 0.9050),
    }
    for (t, m), values in expected.items():
        got = color.wb_gains(PhotoWhiteBalance(t, m))
        assert got == pytest.approx(values, abs=1e-4)
        assert got == pytest.approx(gains(t, m), abs=1e-12)


@pytest.mark.parametrize(("t", "m"), GOLDEN_PAIRS)
def test_luts_match_the_scalar_reference(t: int, m: int) -> None:
    g = color.wb_gains(PhotoWhiteBalance(t, m))
    lut = np.stack([color.channel_lut(gain) for gain in g])
    assert lut.dtype == np.uint8 and lut.shape == (3, 256)
    assert np.array_equal(lut, reference_lut(t, m))
    assert (lut[:, 0] == 0).all()
    assert (np.diff(lut.astype(int), axis=1) >= 0).all()
    assert abs(luminance(g) - 1) < 1e-12


def test_a_unit_gain_lut_is_the_identity() -> None:
    assert np.array_equal(color.channel_lut(1.0), np.arange(256, dtype=np.uint8))


def test_apply_matches_the_per_pixel_oracle_and_mutates_in_place() -> None:
    pixels = noise(9, 13)
    expected = reference_wb(pixels, 37, -58)
    work = pixels.copy()
    color.apply_white_balance(work, PhotoWhiteBalance(37, -58), Event())
    assert np.array_equal(work, expected)


def test_neutral_balance_is_a_hard_bypass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(color, "channel_lut", _boom)
    monkeypatch.setattr(color, "wb_gains", _boom)
    source = source_at(tmp_path)
    work = source.pixels.copy()
    color.apply_white_balance(work, PhotoWhiteBalance(), Event())
    assert np.array_equal(work, source.pixels)
    v2 = update_tone(PhotoEditRecipe(source, (eye(),)), TONE)
    v4 = update_geometry(v2, PhotoGeometry(1, (10, 5, 100, 80), 30))
    v5 = replace(v4, schema_version=5, algorithm_version="photo-color-v1")
    out4 = render(source, v4, cancel=Event())
    render(source, v2, cancel=Event())
    assert np.array_equal(render(source, v5, cancel=Event()), out4)


def test_a_v5_balance_changes_pixels_and_never_touches_the_source(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    before = source.pixels.copy()
    recipe = update_white_balance(PhotoEditRecipe(source), WB)
    out = render(source, recipe, cancel=Event())
    assert not source.pixels.flags.writeable
    assert np.array_equal(source.pixels, before)
    assert np.array_equal(out, reference_wb(before, 100, 0))


def test_render_order_is_geometry_then_white_balance_then_tone(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    balance = PhotoWhiteBalance(100, 40)
    recipe = straight_recipe(source, PhotoGeometry(1, (10, 5, 100, 80)), tone=TONE, eyes=(eye(),))
    recipe = update_white_balance(recipe, balance)
    neutral = replace(recipe, white_balance=PhotoWhiteBalance(), tone=PhotoTone())
    base = render(source, neutral, cancel=Event())
    wb_then_tone = reference_tone(reference_wb(base, 100, 40), TONE)
    tone_then_wb = reference_wb(reference_tone(base, TONE), 100, 40)
    assert not np.array_equal(wb_then_tone, tone_then_wb)
    assert np.array_equal(render(source, recipe, cancel=Event()), wb_then_tone)


def test_tile_boundaries_do_not_change_the_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pixels = noise(11, 17, seed=4)
    source = tone_source(tmp_path, pixels)
    recipe = update_white_balance(PhotoEditRecipe(source), PhotoWhiteBalance(-70, 25))
    whole = render(source, recipe, cancel=Event())
    monkeypatch.setattr(color, "WB_TILE_PIXELS", 7)
    tiled = render(source, recipe, cancel=Event())
    assert np.array_equal(whole, tiled)
    assert np.array_equal(tiled, reference_wb(pixels, -70, 25))


def test_cancel_stops_white_balance_between_tiles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = noise(8, 8)
    cancel = Event()
    cancel.set()
    with pytest.raises(PhotoEditCancelledError):
        color.apply_white_balance(work, WB, cancel)
    cancel = Event()
    monkeypatch.setattr(color, "WB_TILE_PIXELS", 10)
    original = color.check_cancel
    calls = []

    def spy(event: Event) -> None:
        calls.append(1)
        if len(calls) == 2:
            event.set()
        original(event)

    monkeypatch.setattr(color, "check_cancel", spy)
    source = source_at(tmp_path)
    before = source.pixels.copy()
    with pytest.raises(PhotoEditCancelledError):
        render(source, update_white_balance(PhotoEditRecipe(source), WB), cancel=cancel)
    assert len(calls) == 2
    assert np.array_equal(source.pixels, before)


def test_the_angled_preview_applies_white_balance_to_after_and_working(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    plain = straight_recipe(source, PhotoGeometry(0, None, 37), tone=TONE)
    balanced = update_white_balance(plain, WB)
    first = make_preview(source, plain, cache_dir=tmp_path / "a", generation=1, cancel=Event())
    second = make_preview(source, balanced, cache_dir=tmp_path / "b", generation=1, cancel=Event())
    assert first.before.read_bytes() == second.before.read_bytes()
    assert first.after.read_bytes() != second.after.read_bytes()
    assert first.working.read_bytes() != second.working.read_bytes()


def test_the_straight_preview_also_applies_it(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    plain = PhotoEditRecipe(source)
    one = make_preview(source, plain, cache_dir=tmp_path / "a", generation=1, cancel=Event())
    two = make_preview(
        source,
        update_white_balance(plain, WB),
        cache_dir=tmp_path / "b",
        generation=1,
        cancel=Event(),
    )
    assert one.after.read_bytes() != two.after.read_bytes()


def test_saved_recipe_replays_to_the_same_pixels(tmp_path: Path) -> None:
    source = source_at(tmp_path)
    recipe = update_white_balance(PhotoEditRecipe(source, (eye(),)), PhotoWhiteBalance(33, -44))
    again = parse_recipe(recipe_bytes(recipe), source)
    assert np.array_equal(
        render(source, recipe, cancel=Event()), render(source, again, cancel=Event())
    )
    assert json.loads(recipe_bytes(again))["white_balance"] == {"temperature": 33, "tint": -44}
