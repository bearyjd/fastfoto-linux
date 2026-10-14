"""Tone-preserving behaviour: sepia, black and white, dominant colours and saturation recovery."""

import math

import numpy as np
import pytest

from fastfoto_linux.enhance.restore import RestoreSettings, measure_cast, restore_colour
from tests._restore_synth import (
    BEACH_BANDS,
    DPI,
    HEIGHT,
    SUNSET_BAND_WIDTH,
    SUNSET_BANDS,
    WIDTH,
    desaturate,
    hue_error,
    hue_of,
    l_contrast,
    lab,
    make_beach,
    make_faded_black_and_white,
    make_faded_sepia,
    make_natural,
    make_sunset,
    mean_chroma,
    mean_hue,
    patch_mean_ab,
    uniform_with_chroma,
)

MIN_CONTRAST_RATIO = 1.3
SEPIA_CHROMA_BAND = (0.6, 2.5)  # tone kept: neither stripped nor wildly exaggerated
SEPIA_MAX_HUE_SHIFT_DEG = 15.0
BLACK_AND_WHITE_MAX_CHROMA = 2.0
DOMINANT_MIN_CHROMA_KEPT = 0.8
SUNSET_HUE_TOLERANCE_DEG = 10.0
BEACH_HUE_TOLERANCE_DEG = 15.0
BEACH_BAND_ROWS = HEIGHT // 4
# Median mean-LAB-chroma seen in practice: ScanSnap prints about 10.6, Epson `_a` about 13.8.
REALISTIC_CHROMAS = (10.6, 13.8, 22.0)
MAX_HUE_SHIFT_SIN = 0.12
MIN_BOOST_STEP = 0.04


def test_sepia_keeps_its_tone_while_contrast_is_restored() -> None:
    sepia = make_faded_sepia()
    out = restore_colour(sepia, DPI)
    before_a, before_b = measure_cast(sepia)
    after_a, after_b = measure_cast(out)
    assert math.copysign(1, after_a) == math.copysign(1, before_a)  # a*/b* keep their sign
    assert math.copysign(1, after_b) == math.copysign(1, before_b)
    low, high = SEPIA_CHROMA_BAND
    assert low * mean_chroma(sepia) <= mean_chroma(out) <= high * mean_chroma(sepia)
    assert hue_error(mean_hue(sepia), mean_hue(out)) <= SEPIA_MAX_HUE_SHIFT_DEG
    assert l_contrast(out) > MIN_CONTRAST_RATIO * l_contrast(sepia)


def test_pure_black_and_white_print_stays_exactly_neutral_and_gains_contrast() -> None:
    grey = make_faded_black_and_white()
    out = restore_colour(grey, DPI)
    assert np.array_equal(out[..., 0], out[..., 1])
    assert np.array_equal(out[..., 1], out[..., 2])
    assert l_contrast(out) > MIN_CONTRAST_RATIO * l_contrast(grey)


def test_black_and_white_scan_with_channel_noise_stays_neutral_and_gains_contrast() -> None:
    grey = make_faded_black_and_white(noise=1)
    out = restore_colour(grey, DPI)
    assert mean_chroma(out) < BLACK_AND_WHITE_MAX_CHROMA
    assert l_contrast(out) > MIN_CONTRAST_RATIO * l_contrast(grey)


def _band_hue_and_chroma(img: np.ndarray, rows: slice, x0: int, width: int) -> tuple[float, float]:
    a, b = patch_mean_ab(img, rows, x0, width)
    return hue_of(a, b), math.hypot(a, b)


def test_sunset_keeps_hue_ordering_and_most_of_its_chroma() -> None:
    sunset = make_sunset()
    out = restore_colour(sunset, DPI)
    top = slice(0, HEIGHT * 2 // 3)
    before = [
        _band_hue_and_chroma(sunset, top, i * SUNSET_BAND_WIDTH, SUNSET_BAND_WIDTH)
        for i in range(len(SUNSET_BANDS))
    ]
    after = [
        _band_hue_and_chroma(out, top, i * SUNSET_BAND_WIDTH, SUNSET_BAND_WIDTH)
        for i in range(len(SUNSET_BANDS))
    ]
    assert np.argsort([h for h, _ in after]).tolist() == np.argsort([h for h, _ in before]).tolist()
    for (hue_in, chroma_in), (hue_out, chroma_out) in zip(before, after, strict=True):
        assert hue_error(hue_in, hue_out) <= SUNSET_HUE_TOLERANCE_DEG
        assert chroma_out >= DOMINANT_MIN_CHROMA_KEPT * chroma_in
    assert mean_chroma(out) >= DOMINANT_MIN_CHROMA_KEPT * mean_chroma(sunset)


def test_beach_keeps_its_three_hue_families_and_chroma() -> None:
    beach = make_beach()
    out = restore_colour(beach, DPI)
    for i in range(len(BEACH_BANDS)):
        rows = slice(i * BEACH_BAND_ROWS, (i + 1) * BEACH_BAND_ROWS)
        hue_in, chroma_in = _band_hue_and_chroma(beach, rows, 0, WIDTH)
        hue_out, chroma_out = _band_hue_and_chroma(out, rows, 0, WIDTH)
        assert hue_error(hue_in, hue_out) <= BEACH_HUE_TOLERANCE_DEG, f"band {i}"
        assert chroma_out >= DOMINANT_MIN_CHROMA_KEPT * chroma_in, f"band {i}"


# --- saturation recovery is gated on real, measured desaturation --------------------------


@pytest.mark.parametrize("chroma", REALISTIC_CHROMAS)
def test_images_with_realistic_chroma_are_not_boosted(chroma: float) -> None:
    img = uniform_with_chroma(chroma)
    assert np.array_equal(restore_colour(img, DPI), img)


def test_a_natural_photo_is_not_boosted() -> None:
    natural = make_natural()
    assert 10.0 <= mean_chroma(natural) <= 20.0  # the fixture really is at a realistic chroma
    off = restore_colour(natural, DPI, RestoreSettings(saturation_gain=1.0))
    assert np.array_equal(restore_colour(natural, DPI), off)


def test_boost_grows_with_the_chroma_deficit_and_never_exceeds_the_gain() -> None:
    # Isolate the saturation stage: max_gain=1 makes the contrast stretch the identity.
    settings = RestoreSettings(saturation_gain=1.3, max_gain=1.0)
    natural = make_natural()
    ratios = []
    for keep in (0.6, 0.35, 0.15):  # mean chroma about 10.7, 6.2 and 2.7
        dull = desaturate(natural, keep)
        ratios.append(mean_chroma(restore_colour(dull, DPI, settings)) / mean_chroma(dull))
    assert 1.0 <= ratios[0] < ratios[1] < ratios[2] <= settings.saturation_gain + 0.03
    assert ratios[2] > 1.1  # a really dull image is clearly recovered
    assert ratios[2] - ratios[1] > MIN_BOOST_STEP  # ...and a mildly dull one gets less


def test_a_neutral_image_stays_exactly_neutral_when_boosted() -> None:
    grey = uniform_with_chroma(0.0)
    assert np.array_equal(restore_colour(grey, DPI, RestoreSettings(saturation_gain=3.0)), grey)


@pytest.mark.parametrize("hue", [60.0, 230.0])
def test_saturation_boost_keeps_hue(hue: float) -> None:
    img = uniform_with_chroma(6.0, hue_deg=hue)
    out = restore_colour(img, DPI, RestoreSettings(saturation_gain=3.0))
    before, after = lab(img)[0, 0], lab(out)[0, 0]
    assert math.hypot(after[1], after[2]) > 1.5 * math.hypot(before[1], before[2])
    hue_shift = math.atan2(after[2], after[1]) - math.atan2(before[2], before[1])
    assert abs(math.sin(hue_shift)) < MAX_HUE_SHIFT_SIN
