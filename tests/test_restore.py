"""Colour restoration on synthetic prints (no private scans): assert DIRECTION, not "it changed"."""

import dataclasses
import math

import numpy as np
import pytest

from fastfoto_linux.enhance.restore import DEFAULT, RestoreSettings, measure_cast, restore_colour
from tests._restore_synth import (
    DPI,
    NEUTRAL_PATCH_LEVELS,
    NEUTRAL_PATCH_WIDTH,
    NEUTRAL_ROWS,
    RAMP_ROWS,
    SEED,
    colour_hues,
    cyclic_order,
    fade_with_cast,
    hue_error,
    l_contrast,
    lab,
    local_contrast,
    make_reference,
    mean_abs_change,
    patch_mean_ab,
)

MIN_CAST_BEFORE = 12.0  # sanity: the synthetic fade really is a visible cast
CAST_REDUCTION = 0.5
NEUTRAL_TOLERANCE = 1.5
MIN_CONTRAST_RATIO = 1.3
IDEMPOTENT_MAX_MEAN_CHANGE = 3.0
UNIFORM_MAX_MEAN_CHANGE = 8.0
HUE_TOLERANCE_DEG = 10.0
MIN_CLAHE_GAIN = 1.1
# Strong per-channel tone-curve differences (a nonlinear dye fade). A linear per-channel stretch
# cannot undo curvature, so only part of the cast goes; mid-tone balance is a follow-up.
SKEWED_GAMMAS = (0.8, 1.3, 1.0)
SKEWED_MIN_REDUCTION = 0.4


@pytest.fixture(scope="module")
def reference() -> np.ndarray:
    return make_reference()


@pytest.fixture(scope="module")
def faded(reference: np.ndarray) -> np.ndarray:
    return fade_with_cast(reference)


@pytest.fixture(scope="module")
def restored(faded: np.ndarray) -> np.ndarray:
    return restore_colour(faded, DPI)


# --- the fixture itself must really be a faded, cast print --------------------------------


def test_synthetic_fade_is_a_visible_cast_with_lower_contrast(
    reference: np.ndarray, faded: np.ndarray
) -> None:
    a, b = measure_cast(faded[RAMP_ROWS])
    assert math.hypot(a, b) > MIN_CAST_BEFORE
    assert l_contrast(faded) < l_contrast(reference)


# --- direction of the correction ----------------------------------------------------------


def test_cast_on_neutral_ramp_moves_toward_zero_by_half_or_more(
    faded: np.ndarray, restored: np.ndarray
) -> None:
    before_a, before_b = measure_cast(faded[RAMP_ROWS])
    after_a, after_b = measure_cast(restored[RAMP_ROWS])
    assert math.hypot(after_a, after_b) <= CAST_REDUCTION * math.hypot(before_a, before_b)
    for before, after in ((before_a, after_a), (before_b, after_b)):
        if abs(before) > MIN_CAST_BEFORE / 2:
            assert abs(after) <= CAST_REDUCTION * abs(before)


def test_cast_from_a_strongly_nonlinear_fade_is_still_substantially_reduced(
    reference: np.ndarray,
) -> None:
    skewed = fade_with_cast(reference, SKEWED_GAMMAS)
    before_a, before_b = measure_cast(skewed[RAMP_ROWS])
    after_a, after_b = measure_cast(restore_colour(skewed, DPI)[RAMP_ROWS])
    assert math.hypot(before_a, before_b) > MIN_CAST_BEFORE
    reduced_to = math.hypot(after_a, after_b) / math.hypot(before_a, before_b)
    assert reduced_to <= 1.0 - SKEWED_MIN_REDUCTION


def test_contrast_of_lightness_increases(faded: np.ndarray, restored: np.ndarray) -> None:
    assert l_contrast(restored) > MIN_CONTRAST_RATIO * l_contrast(faded)


def test_neutral_patches_end_near_neutral(restored: np.ndarray) -> None:
    for i in range(len(NEUTRAL_PATCH_LEVELS)):
        a, b = patch_mean_ab(restored, NEUTRAL_ROWS, i * NEUTRAL_PATCH_WIDTH, NEUTRAL_PATCH_WIDTH)
        assert abs(a) < NEUTRAL_TOLERANCE, f"patch {i}: |a*|={abs(a):.2f}"
        assert abs(b) < NEUTRAL_TOLERANCE, f"patch {i}: |b*|={abs(b):.2f}"


def test_colour_patches_keep_their_hue_ordering(
    reference: np.ndarray, faded: np.ndarray, restored: np.ndarray
) -> None:
    wanted = cyclic_order(colour_hues(reference))
    assert cyclic_order(colour_hues(faded)) == wanted  # the fade alone must not reorder
    assert cyclic_order(colour_hues(restored)) == wanted


def test_colour_hues_move_back_toward_the_original(
    reference: np.ndarray, faded: np.ndarray, restored: np.ndarray
) -> None:
    ref = colour_hues(reference)
    before = [hue_error(h, r) for h, r in zip(colour_hues(faded), ref, strict=True)]
    after = [hue_error(h, r) for h, r in zip(colour_hues(restored), ref, strict=True)]
    assert sum(after) < sum(before)
    assert max(after) < HUE_TOLERANCE_DEG < max(before)


# --- safeguards ---------------------------------------------------------------------------


def test_restoring_twice_is_close_to_restoring_once(restored: np.ndarray) -> None:
    again = restore_colour(restored, DPI)
    assert mean_abs_change(again, restored) < IDEMPOTENT_MAX_MEAN_CHANGE


@pytest.mark.parametrize("colour", [(0, 0, 0), (255, 255, 255), (128, 128, 128)])
def test_uniform_neutral_image_is_returned_unchanged(colour: tuple[int, int, int]) -> None:
    img = np.full((60, 80, 3), colour, dtype=np.uint8)
    out = restore_colour(img, DPI)
    assert np.array_equal(out, img)


@pytest.mark.parametrize("colour", [(180, 150, 120), (200, 60, 60), (30, 40, 90)])
def test_uniform_coloured_image_is_finite_and_nearly_unchanged(
    colour: tuple[int, int, int],
) -> None:
    img = np.full((60, 80, 3), colour, dtype=np.uint8)
    out = restore_colour(img, DPI)
    assert out.shape == img.shape
    assert out.dtype == np.uint8
    assert mean_abs_change(out, img) < UNIFORM_MAX_MEAN_CHANGE


# --- contract: shape, dtype, purity, resolution independence ------------------------------


def test_shape_and_dtype_preserved_and_input_untouched(faded: np.ndarray) -> None:
    snapshot = faded.copy()
    readonly = faded.copy()
    readonly.flags.writeable = False
    out = restore_colour(readonly, DPI)
    assert out.shape == faded.shape
    assert out.dtype == np.uint8
    assert not np.shares_memory(out, readonly)
    assert np.array_equal(readonly, snapshot)


def test_unchanged_result_is_still_a_new_array() -> None:
    img = np.full((20, 30, 3), 128, dtype=np.uint8)
    out = restore_colour(img, DPI)
    assert np.array_equal(out, img)
    assert not np.shares_memory(out, img)


def test_clahe_adds_local_contrast_and_preserves_contract() -> None:
    rng = np.random.default_rng(SEED)
    gradient = np.linspace(90, 170, 320)[None, :, None] + rng.normal(0.0, 4.0, (200, 320, 3))
    flat = np.clip(np.rint(gradient), 0, 255).astype(np.uint8)
    plain = restore_colour(flat, DPI)
    local = restore_colour(flat, DPI, dataclasses.replace(DEFAULT, clahe=True))
    assert local.shape == flat.shape
    assert local.dtype == np.uint8
    assert local_contrast(local) > MIN_CLAHE_GAIN * local_contrast(plain)


def test_default_settings_are_the_documented_ones() -> None:
    assert RestoreSettings() == DEFAULT
    assert DEFAULT.clahe is False  # local contrast is opt-in


# --- validation ---------------------------------------------------------------------------


def test_settings_are_immutable() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        DEFAULT.max_gain = 9.0  # type: ignore[misc]


@pytest.mark.parametrize(
    "bad",
    [
        {"low_clip_pct": -0.1},
        {"high_clip_pct": -1.0},
        {"low_clip_pct": 50.0},
        {"high_clip_pct": 60.0},
        {"low_clip_pct": math.nan},
        {"high_clip_pct": math.inf},
        {"max_gain": 0.9},
        {"max_gain": math.inf},
        {"max_gain": math.nan},
        {"saturation_gain": 0.0},
        {"saturation_gain": -1.0},
        {"saturation_gain": 0.5},
        {"saturation_gain": 3.5},
        {"saturation_gain": math.inf},
        {"saturation_gain": math.nan},
    ],
)
def test_invalid_settings_are_rejected(bad: dict[str, float]) -> None:
    with pytest.raises(ValueError, match=next(iter(bad))):
        RestoreSettings(**bad)


def test_the_documented_saturation_gain_range_is_accepted() -> None:
    assert RestoreSettings(saturation_gain=1.0).saturation_gain == 1.0
    assert RestoreSettings(saturation_gain=3.0).saturation_gain == 3.0


@pytest.mark.parametrize(
    "img",
    [
        np.zeros((10, 10, 3), dtype=np.float32),
        np.zeros((10, 10), dtype=np.uint8),
        np.zeros((10, 10, 4), dtype=np.uint8),
        np.zeros((0, 10, 3), dtype=np.uint8),
    ],
    ids=["float", "grey", "rgba", "empty"],
)
def test_unsupported_images_are_rejected(img: np.ndarray) -> None:
    with pytest.raises(ValueError, match="uint8 RGB"):
        restore_colour(img, DPI)
    with pytest.raises(ValueError, match="uint8 RGB"):
        measure_cast(img)


@pytest.mark.parametrize("dpi", [0, -300, math.nan, math.inf])
def test_non_positive_dpi_is_rejected(dpi: float) -> None:
    with pytest.raises(ValueError, match="dpi"):
        restore_colour(np.zeros((10, 10, 3), dtype=np.uint8), dpi)


# --- measure_cast -------------------------------------------------------------------------


def test_measure_cast_is_zero_for_grey_and_signed_for_colours() -> None:
    def cast(rgb: tuple[int, int, int]) -> tuple[float, float]:
        return measure_cast(np.full((8, 8, 3), rgb, dtype=np.uint8))

    grey_a, grey_b = cast((128, 128, 128))
    assert abs(grey_a) < 0.5
    assert abs(grey_b) < 0.5
    assert cast((220, 40, 150))[0] > 0  # magenta/red: positive a*
    assert cast((40, 200, 90))[0] < 0  # green: negative a*
    assert cast((220, 200, 40))[1] > 0  # yellow: positive b*
    assert cast((40, 80, 220))[1] < 0  # blue: negative b*


def test_measure_cast_is_the_mean_of_a_and_b_channels(faded: np.ndarray) -> None:
    expected = lab(faded)
    a, b = measure_cast(faded)
    assert a == pytest.approx(float(expected[..., 1].mean()), abs=1e-3)
    assert b == pytest.approx(float(expected[..., 2].mean()), abs=1e-3)
