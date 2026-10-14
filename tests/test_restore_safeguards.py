"""Safeguards: exact clipping, scanner frames, low-key scenes, balanced and degenerate inputs."""

import numpy as np
import pytest

from fastfoto_linux.enhance.restore import DEFAULT, RestoreSettings, measure_cast, restore_colour
from tests._restore_synth import (
    DPI,
    FULL_SCALE,
    NIGHT_UNLIT_BACKGROUND,
    RAMP_ROWS,
    SEED,
    clipped_fractions,
    fade_with_cast,
    grey_of,
    lab,
    make_natural,
    make_night_scene,
    make_reference,
    mean_abs_change,
    uniform_with_chroma,
)

HIGH_DPI = 600
MAX_CHANNEL_GAIN_RATIO = 1.3
CLIP_PCT = 0.5
CLIP_TOLERANCE = 0.001  # fraction of pixels: quantisation of a continuous tail
BALANCED_MAX_MEAN_CHANGE = 3.5
FRAME_PX = 20
FRAME_CAST_REDUCTION = 0.5
FRAME_INTERIOR_MAX_CHANGE = 1.0
NIGHT_MIN_P1_KEPT = 0.75  # fraction of the original 1st percentile that must survive
NIGHT_MAX_MEAN_SHIFT = (
    15.0  # grey levels: brightening is capped by max_gain, darkening by the black-point rule
)
NIGHT_MIN_P1 = 30.0  # the fixture starts with lifted blacks, not real black
HEAVY_BIN_FRACTION = 0.03
HEAVY_BIN_LEVEL = 8


# --- clipping is exactly what the settings say, at any dpi ---------------------------------


@pytest.mark.parametrize("dpi", [DPI, HIGH_DPI])
def test_clipped_pixels_per_channel_stay_within_the_configured_tails(dpi: int) -> None:
    grainy = make_natural(texture=25.0)  # fine grain a downsampled analysis would average away
    faded = fade_with_cast(grainy)
    assert clipped_fractions(faded) == (0.0, 0.0)
    low, high = clipped_fractions(restore_colour(faded, dpi))
    assert low <= CLIP_PCT / 100.0 + CLIP_TOLERANCE
    assert high <= CLIP_PCT / 100.0 + CLIP_TOLERANCE


def test_a_heavy_level_at_the_tail_is_not_clipped_wholesale() -> None:
    base = make_natural()
    rng = np.random.default_rng(SEED)
    dark = rng.random(base.shape[:2]) < HEAVY_BIN_FRACTION
    base[dark] = HEAVY_BIN_LEVEL  # a few percent of pixels share one very dark level
    low, _ = clipped_fractions(restore_colour(fade_with_cast(base), DPI))
    assert low <= CLIP_PCT / 100.0 + CLIP_TOLERANCE


def test_resolution_does_not_change_the_result() -> None:
    faded = fade_with_cast(make_reference())
    doubled = np.repeat(np.repeat(faded, 2, axis=0), 2, axis=1)
    small = restore_colour(faded, DPI)
    assert np.array_equal(restore_colour(doubled, 2 * DPI), np.repeat(np.repeat(small, 2, 0), 2, 1))
    assert np.array_equal(restore_colour(faded, HIGH_DPI), small)  # dpi only sizes CLAHE tiles


# --- scanner frame ------------------------------------------------------------------------


def _with_scanner_frame(img: np.ndarray, black: int, white: int) -> np.ndarray:
    pad = ((FRAME_PX, FRAME_PX), (FRAME_PX, FRAME_PX), (0, 0))
    return np.pad(np.pad(img, pad, constant_values=black), pad, constant_values=white)


# Real scans: JPEG never holds exact 0 / 255, and a ScanSnap white margin is about 250-252.
@pytest.mark.parametrize(
    ("black", "white"), [(0, 255), (1, 254), (2, 253), (5, 252), (5, 250), (6, 248)]
)
def test_a_black_and_white_frame_does_not_pin_the_percentiles(black: int, white: int) -> None:
    faded = fade_with_cast(make_reference())
    framed = _with_scanner_frame(faded, black, white)
    out = restore_colour(framed, DPI)
    inside = out[2 * FRAME_PX : -2 * FRAME_PX, 2 * FRAME_PX : -2 * FRAME_PX]
    before = measure_cast(faded[RAMP_ROWS])
    after = measure_cast(inside[RAMP_ROWS])
    assert np.hypot(*after) <= FRAME_CAST_REDUCTION * np.hypot(*before)
    assert mean_abs_change(inside, restore_colour(faded, DPI)) < FRAME_INTERIOR_MAX_CHANGE
    ring = np.ones(framed.shape[:2], dtype=bool)
    ring[2 * FRAME_PX : -2 * FRAME_PX, 2 * FRAME_PX : -2 * FRAME_PX] = False
    assert np.array_equal(out[ring], framed[ring])  # the frame itself is untouched


def test_an_image_that_is_entirely_frame_is_returned_unchanged() -> None:
    img = np.zeros((40, 50, 3), dtype=np.uint8)
    img[:, 25:] = FULL_SCALE
    assert np.array_equal(restore_colour(img, DPI), img)


# --- low-key scenes -----------------------------------------------------------------------


def test_a_dark_night_scene_is_not_crushed() -> None:
    night = make_night_scene()
    out = restore_colour(night, DPI)
    before, after = grey_of(night), grey_of(out)
    p1_before = float(np.percentile(before, 1))
    assert p1_before > NIGHT_MIN_P1
    assert float(np.percentile(after, 1)) >= NIGHT_MIN_P1_KEPT * p1_before
    assert abs(float(after.mean()) - float(before.mean())) <= NIGHT_MAX_MEAN_SHIFT


def test_an_unlit_night_scene_is_not_brightened_much() -> None:
    unlit = make_night_scene(lights=False, background=NIGHT_UNLIT_BACKGROUND)
    before, after = grey_of(unlit), grey_of(restore_colour(unlit, DPI))
    assert abs(float(after.mean()) - float(before.mean())) <= NIGHT_MAX_MEAN_SHIFT


# --- balanced and degenerate inputs -------------------------------------------------------


def test_a_well_balanced_natural_photo_changes_little() -> None:
    natural = make_natural()
    assert mean_abs_change(restore_colour(natural, DPI), natural) < BALANCED_MAX_MEAN_CHANGE


def test_nearly_flat_neutral_image_is_left_alone() -> None:
    rng = np.random.default_rng(SEED)
    noise = rng.integers(-2, 3, (60, 80, 1), dtype=np.int16)
    img = np.broadcast_to(np.uint8(128 + noise), (60, 80, 3)).copy()
    assert np.array_equal(restore_colour(img, DPI), img)


def test_channel_gain_is_capped() -> None:
    img = make_reference()
    narrow = img.copy()
    narrow[..., 0] = np.rint(100 + img[..., 0] / 255.0 * 40).astype(np.uint8)  # 40-level range
    span_before = int(narrow[..., 0].max()) - int(narrow[..., 0].min())
    out = restore_colour(narrow, DPI, RestoreSettings(saturation_gain=1.0))
    span_after = int(out[..., 0].max()) - int(out[..., 0].min())
    assert span_after > 1.5 * span_before  # stretched...
    assert span_after <= DEFAULT.max_gain * span_before + 2  # ...but not beyond the cap


def test_relative_gain_between_channels_is_bounded() -> None:
    img = make_reference()
    img[..., 0] = np.rint(100 + img[..., 0] / 255.0 * 40).astype(np.uint8)  # red: 40 levels
    img[..., 1] = np.rint(30 + img[..., 1] / 255.0 * 200).astype(np.uint8)  # green: 200 levels
    out = restore_colour(img, DPI, RestoreSettings(saturation_gain=1.0))

    def gain(channel: int) -> float:
        before = int(img[..., channel].max()) - int(img[..., channel].min())
        return (int(out[..., channel].max()) - int(out[..., channel].min())) / before

    assert gain(0) / gain(1) <= MAX_CHANNEL_GAIN_RATIO + 0.05


def test_bright_pixels_inside_the_photo_are_not_mistaken_for_a_frame() -> None:
    faded = fade_with_cast(make_reference())
    faded[100:130, 150:200] = FULL_SCALE  # a specular highlight, not touching any edge
    out = restore_colour(faded, DPI)
    assert np.array_equal(out[100:130, 150:200], faded[100:130, 150:200])
    inside = out[:, :150]  # the rest is still corrected
    assert np.hypot(*measure_cast(inside[RAMP_ROWS])) <= FRAME_CAST_REDUCTION * np.hypot(
        *measure_cast(faded[:, :150][RAMP_ROWS])
    )


def test_default_gain_cap_is_conservative() -> None:
    assert DEFAULT.max_gain == pytest.approx(2.0)


def test_channel_already_spanning_the_full_scale_is_left_alone() -> None:
    img = make_reference()
    img[..., 1] = np.rint(40 + img[..., 1] / 255.0 * 160).astype(np.uint8)
    out = restore_colour(img, DPI, RestoreSettings(saturation_gain=1.0))
    assert np.array_equal(out[..., 0], img[..., 0])  # red spans 0-255: not touched
    assert not np.array_equal(out[..., 1], img[..., 1])  # green was compressed: stretched


def test_a_dark_image_with_a_bright_highlight_is_not_stretched() -> None:
    rng = np.random.default_rng(SEED)
    grey = np.clip(rng.normal(30.0, 8.0, (120, 160)), 12, 60)
    grey[rng.random(grey.shape) < 0.02] = 250  # lights: the white point is already there
    img = np.repeat(np.rint(grey).astype(np.uint8)[..., None], 3, axis=2)
    assert np.array_equal(restore_colour(img, DPI), img)


def test_two_opposite_colours_without_any_mean_colour_are_not_flattened() -> None:
    img = np.concatenate([uniform_with_chroma(20.0, 0.0), uniform_with_chroma(20.0, 180.0)], axis=1)
    out = restore_colour(img, DPI)
    assert out.shape == img.shape
    left, right = lab(out)[:, :80, 1].mean(), lab(out)[:, 80:, 1].mean()
    assert left > 0 > right  # still a red half and a green half


def test_a_thin_line_on_a_large_frame_does_not_crash_and_leaves_the_frame_alone() -> None:
    img = np.full((600, 1000, 3), FULL_SCALE, dtype=np.uint8)
    img[:, 500] = 100
    out = restore_colour(img, DPI)
    assert out.shape == img.shape
    assert np.array_equal(out[:, :500], img[:, :500])
