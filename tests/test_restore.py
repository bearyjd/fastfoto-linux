"""Colour restoration on synthetic prints (no private scans): assert DIRECTION, not "it changed"."""

import dataclasses
import math

import cv2
import numpy as np
import pytest

from fastfoto_linux.enhance.restore import DEFAULT, RestoreSettings, measure_cast, restore_colour

DPI = 150
HEIGHT, WIDTH = 240, 360
RAMP_ROWS = slice(0, 80)
PATCH_ROWS = slice(80, 160)
NEUTRAL_ROWS = slice(160, 240)

COLOUR_PATCH_WIDTH = 60
COLOUR_PATCHES = (  # red, yellow, green, cyan, blue, magenta
    (200, 60, 60),
    (210, 200, 60),
    (60, 170, 70),
    (60, 180, 190),
    (60, 80, 200),
    (190, 60, 180),
)
NEUTRAL_PATCH_WIDTH = 90
NEUTRAL_PATCH_LEVELS = (40, 100, 160, 215)
TEXTURE_SIGMA = 8.0
SEED = 20261013

# A magenta/red cast with compressed range and lifted blacks, per channel (R, G, B).
FADE_LOW = (55.0, 30.0, 45.0)
FADE_HIGH = (215.0, 165.0, 190.0)

MIN_CAST_BEFORE = 12.0  # sanity: the synthetic fade really is a visible cast
CAST_REDUCTION = 0.5
NEUTRAL_TOLERANCE = 1.5
MIN_CONTRAST_RATIO = 1.3
BALANCED_MAX_MEAN_CHANGE = 2.0
UNIFORM_MAX_MEAN_CHANGE = 8.0
IDEMPOTENT_MAX_MEAN_CHANGE = 3.0
HUE_TOLERANCE_DEG = 10.0
SKEWED_GAMMAS = (0.9, 1.15, 1.0)  # a nonlinear fade: per channel tone curves differ
MIN_CLAHE_GAIN = 1.1
MAX_HUE_SHIFT_SIN = 0.1


def _lab(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img.astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB)


def _mean_abs_change(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.mean(np.abs(a.astype(np.float32) - b.astype(np.float32))))


def _make_reference() -> np.ndarray:
    """Well-balanced test card: grey ramp, six colour patches, textured neutral patches."""
    rng = np.random.default_rng(SEED)
    img = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    ramp = np.rint(np.linspace(0, 255, WIDTH)).astype(np.uint8)
    img[RAMP_ROWS] = ramp[None, :, None]
    for i, colour in enumerate(COLOUR_PATCHES):
        x0 = i * COLOUR_PATCH_WIDTH
        img[PATCH_ROWS, x0 : x0 + COLOUR_PATCH_WIDTH] = colour
    for i, level in enumerate(NEUTRAL_PATCH_LEVELS):
        x0 = i * NEUTRAL_PATCH_WIDTH
        rows = NEUTRAL_ROWS.stop - NEUTRAL_ROWS.start
        noise = rng.normal(0.0, TEXTURE_SIGMA, (rows, NEUTRAL_PATCH_WIDTH, 1))
        patch = np.clip(np.rint(level + noise), 0, 255).astype(np.uint8)
        img[NEUTRAL_ROWS, x0 : x0 + NEUTRAL_PATCH_WIDTH] = patch
    return img


def _fade_with_cast(img: np.ndarray, gammas: tuple[float, ...] = (1.0, 1.0, 1.0)) -> np.ndarray:
    low = np.array(FADE_LOW, dtype=np.float32)
    high = np.array(FADE_HIGH, dtype=np.float32)
    tone = (img.astype(np.float32) / 255.0) ** np.array(gammas, dtype=np.float32)
    return np.rint(low + tone * (high - low)).astype(np.uint8)


def _patch_mean_ab(img: np.ndarray, rows: slice, x0: int, width: int) -> tuple[float, float]:
    margin = width // 4
    region = _lab(img)[rows, x0 + margin : x0 + width - margin]
    return float(region[..., 1].mean()), float(region[..., 2].mean())


def _colour_hues(img: np.ndarray) -> list[float]:
    hues = []
    for i in range(len(COLOUR_PATCHES)):
        a, b = _patch_mean_ab(img, PATCH_ROWS, i * COLOUR_PATCH_WIDTH, COLOUR_PATCH_WIDTH)
        hues.append(math.degrees(math.atan2(b, a)) % 360.0)
    return hues


def _cyclic_order(hues: list[float]) -> tuple[int, ...]:
    """Patch indices sorted by hue angle, rotated to start at patch 0 (hue wraps at 360)."""
    order = sorted(range(len(hues)), key=hues.__getitem__)
    start = order.index(0)
    return tuple(order[start:] + order[:start])


def _hue_error(a: float, b: float) -> float:
    diff = abs(a - b) % 360.0
    return min(diff, 360.0 - diff)


def _l_contrast(img: np.ndarray) -> float:
    lightness = _lab(img)[..., 0]
    return float(np.percentile(lightness, 99) - np.percentile(lightness, 1))


def _local_contrast(img: np.ndarray) -> float:
    lightness = _lab(img)[..., 0]
    return float(np.std(lightness - cv2.blur(lightness, (9, 9))))


def _mean_chroma(img: np.ndarray) -> float:
    lab = _lab(img)
    return float(np.mean(np.hypot(lab[..., 1], lab[..., 2])))


@pytest.fixture(scope="module")
def reference() -> np.ndarray:
    return _make_reference()


@pytest.fixture(scope="module")
def faded(reference: np.ndarray) -> np.ndarray:
    return _fade_with_cast(reference)


@pytest.fixture(scope="module")
def restored(faded: np.ndarray) -> np.ndarray:
    return restore_colour(faded, DPI)


# --- the fixture itself must really be a faded, cast print --------------------------------


def test_synthetic_fade_is_a_visible_cast_with_lower_contrast(
    reference: np.ndarray, faded: np.ndarray
) -> None:
    a, b = measure_cast(faded[RAMP_ROWS])
    assert math.hypot(a, b) > MIN_CAST_BEFORE
    assert _l_contrast(faded) < _l_contrast(reference)


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


def test_cast_from_a_nonlinear_fade_is_still_at_least_halved(reference: np.ndarray) -> None:
    skewed = _fade_with_cast(reference, SKEWED_GAMMAS)
    before_a, before_b = measure_cast(skewed[RAMP_ROWS])
    after_a, after_b = measure_cast(restore_colour(skewed, DPI)[RAMP_ROWS])
    assert math.hypot(before_a, before_b) > MIN_CAST_BEFORE
    assert math.hypot(after_a, after_b) <= CAST_REDUCTION * math.hypot(before_a, before_b)


def test_contrast_of_lightness_increases(faded: np.ndarray, restored: np.ndarray) -> None:
    assert _l_contrast(restored) > MIN_CONTRAST_RATIO * _l_contrast(faded)


def test_neutral_patches_end_near_neutral(restored: np.ndarray) -> None:
    for i in range(len(NEUTRAL_PATCH_LEVELS)):
        a, b = _patch_mean_ab(restored, NEUTRAL_ROWS, i * NEUTRAL_PATCH_WIDTH, NEUTRAL_PATCH_WIDTH)
        assert abs(a) < NEUTRAL_TOLERANCE, f"patch {i}: |a*|={abs(a):.2f}"
        assert abs(b) < NEUTRAL_TOLERANCE, f"patch {i}: |b*|={abs(b):.2f}"


def test_colour_patches_keep_their_hue_ordering(
    reference: np.ndarray, faded: np.ndarray, restored: np.ndarray
) -> None:
    wanted = _cyclic_order(_colour_hues(reference))
    assert _cyclic_order(_colour_hues(faded)) == wanted  # the fade alone must not reorder
    assert _cyclic_order(_colour_hues(restored)) == wanted


def test_colour_hues_move_back_toward_the_original(
    reference: np.ndarray, faded: np.ndarray, restored: np.ndarray
) -> None:
    ref = _colour_hues(reference)
    before = [_hue_error(h, r) for h, r in zip(_colour_hues(faded), ref, strict=True)]
    after = [_hue_error(h, r) for h, r in zip(_colour_hues(restored), ref, strict=True)]
    assert sum(after) < sum(before)
    assert max(after) < HUE_TOLERANCE_DEG < max(before)


# --- safeguards ---------------------------------------------------------------------------


def test_well_balanced_image_changes_little(reference: np.ndarray) -> None:
    assert _mean_abs_change(restore_colour(reference, DPI), reference) < BALANCED_MAX_MEAN_CHANGE


def test_restoring_twice_is_close_to_restoring_once(restored: np.ndarray) -> None:
    again = restore_colour(restored, DPI)
    assert _mean_abs_change(again, restored) < IDEMPOTENT_MAX_MEAN_CHANGE


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
    assert _mean_abs_change(out, img) < UNIFORM_MAX_MEAN_CHANGE


def test_nearly_flat_neutral_image_is_left_alone() -> None:
    rng = np.random.default_rng(SEED)
    noise = rng.integers(-2, 3, (60, 80, 1), dtype=np.int16)
    img = np.broadcast_to(np.uint8(128 + noise), (60, 80, 3)).copy()
    assert np.array_equal(restore_colour(img, DPI), img)


def test_channel_gain_is_capped() -> None:
    img = _make_reference()
    narrow = img.copy()
    narrow[..., 0] = np.rint(100 + img[..., 0] / 255.0 * 40).astype(np.uint8)  # 40-level range
    span_before = int(narrow[..., 0].max()) - int(narrow[..., 0].min())
    out = restore_colour(narrow, DPI, RestoreSettings(saturation_gain=1.0))
    span_after = int(out[..., 0].max()) - int(out[..., 0].min())
    assert span_after > 2 * span_before  # stretched...
    assert span_after <= DEFAULT.max_gain * span_before + 2  # ...but not beyond the cap


def test_channel_already_spanning_the_full_scale_is_left_alone() -> None:
    img = _make_reference()
    img[..., 1] = np.rint(40 + img[..., 1] / 255.0 * 160).astype(np.uint8)
    out = restore_colour(img, DPI, RestoreSettings(saturation_gain=1.0))
    assert np.array_equal(out[..., 0], img[..., 0])  # red spans 0-255: not touched
    assert not np.array_equal(out[..., 1], img[..., 1])  # green was compressed: stretched


def test_saturation_is_recovered_only_when_the_image_is_desaturated() -> None:
    dull = np.full((60, 80, 3), (150, 135, 128), dtype=np.uint8)
    vivid = np.full((60, 80, 3), (200, 60, 60), dtype=np.uint8)
    boosted = restore_colour(dull, DPI)
    assert _mean_chroma(boosted) > 1.05 * _mean_chroma(dull)
    off = restore_colour(dull, DPI, RestoreSettings(saturation_gain=1.0))
    assert np.array_equal(off, dull)
    assert np.array_equal(restore_colour(vivid, DPI), vivid)  # already saturated: gate closed


@pytest.mark.parametrize("colour", [(150, 120, 100), (110, 125, 140)])
def test_saturation_boost_keeps_hue(colour: tuple[int, int, int]) -> None:
    img = np.full((60, 80, 3), colour, dtype=np.uint8)
    out = restore_colour(img, DPI, RestoreSettings(saturation_gain=2.0))
    before, after = _lab(img)[0, 0], _lab(out)[0, 0]
    assert math.hypot(after[1], after[2]) > 1.5 * math.hypot(before[1], before[2])
    hue_shift = math.atan2(after[2], after[1]) - math.atan2(before[2], before[1])
    assert abs(math.sin(hue_shift)) < MAX_HUE_SHIFT_SIN


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


def test_high_resolution_input_is_analysed_on_a_downsampled_copy_with_same_result(
    faded: np.ndarray,
) -> None:
    doubled = np.repeat(np.repeat(faded, 2, axis=0), 2, axis=1)
    small = restore_colour(faded, DPI)
    big = restore_colour(doubled, 2 * DPI)
    assert np.array_equal(big, np.repeat(np.repeat(small, 2, axis=0), 2, axis=1))


def test_percentiles_are_measured_on_a_downsampled_copy_at_high_dpi() -> None:
    checker = np.indices((64, 64)).sum(axis=0) % 2 * 200  # 1-pixel squares of 0 and 200
    img = np.repeat(checker.astype(np.uint8)[..., None], 3, axis=2)
    assert not np.array_equal(restore_colour(img, DPI), img)  # analysed at full size: stretched
    assert np.array_equal(restore_colour(img, 4 * DPI), img)  # averaged to flat grey: left alone


def test_clahe_adds_local_contrast_and_preserves_contract() -> None:
    rng = np.random.default_rng(SEED)
    gradient = np.linspace(90, 170, 320)[None, :, None] + rng.normal(0.0, 4.0, (200, 320, 3))
    flat = np.clip(np.rint(gradient), 0, 255).astype(np.uint8)
    plain = restore_colour(flat, DPI)
    local = restore_colour(flat, DPI, dataclasses.replace(DEFAULT, clahe=True))
    assert local.shape == flat.shape
    assert local.dtype == np.uint8
    assert _local_contrast(local) > MIN_CLAHE_GAIN * _local_contrast(plain)


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
        {"max_gain": 0.9},
        {"saturation_gain": 0.0},
        {"saturation_gain": -1.0},
    ],
)
def test_invalid_settings_are_rejected(bad: dict[str, float]) -> None:
    with pytest.raises(ValueError, match=next(iter(bad))):
        RestoreSettings(**bad)


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


@pytest.mark.parametrize("dpi", [0, -300])
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
    lab = _lab(faded)
    a, b = measure_cast(faded)
    assert a == pytest.approx(float(lab[..., 1].mean()), abs=1e-3)
    assert b == pytest.approx(float(lab[..., 2].mean()), abs=1e-3)
