"""Tone-preserving behaviour: sepia, black and white, dominant colours and saturation recovery."""

import dataclasses
import math

import numpy as np
import pytest

from fastfoto_linux.enhance.restore import RestoreSettings, measure_cast, restore_colour
from tests._restore_scenes import (
    make_dominant_hue,
    make_near_white_page,
    make_sepia_with_ink,
    make_tinted_black_and_white,
    paper_chroma,
    paper_level,
)
from tests._restore_synth import (
    BEACH_BANDS,
    DPI,
    HEIGHT,
    WIDTH,
    desaturate,
    hue_error,
    hue_of,
    l_contrast,
    lab,
    make_beach,
    make_faded_black_and_white,
    make_faded_orange_glow,
    make_faded_sepia,
    make_natural,
    mean_chroma,
    mean_hue,
    patch_mean_ab,
    uniform_with_chroma,
)

MIN_CONTRAST_RATIO = 1.3
TONE_CHROMA_BAND = (0.85, 1.15)  # a tone is kept as it is: not stripped, not amplified
TONE_MAX_HUE_SHIFT_DEG = 15.0
BLACK_AND_WHITE_MAX_CHROMA = 2.0
DOMINANT_MIN_CHROMA_KEPT = 0.8
SCENE_MIN_CHROMA_KEPT = 0.5  # a one-hue scene keeps at least half of its colour
TINT_MAX_GROWTH = 1.1
PAPER_MAX_CHANGE = 1.0  # levels
INK_FRACTIONS = (0.005, 0.01, 0.03, 0.05)  # a few percent of the print
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
    low, high = TONE_CHROMA_BAND
    assert low * mean_chroma(sepia) <= mean_chroma(out) <= high * mean_chroma(sepia)
    assert hue_error(mean_hue(sepia), mean_hue(out)) <= TONE_MAX_HUE_SHIFT_DEG
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


def _assert_tone_kept(before: np.ndarray, after: np.ndarray) -> None:
    low, high = TONE_CHROMA_BAND
    assert low * mean_chroma(before) <= mean_chroma(after) <= high * mean_chroma(before)
    assert hue_error(mean_hue(before), mean_hue(after)) <= TONE_MAX_HUE_SHIFT_DEG


def test_single_hue_glow_keeps_its_hue_and_chroma() -> None:
    glow = make_faded_orange_glow()
    out = restore_colour(glow, DPI)
    _assert_tone_kept(glow, out)
    assert l_contrast(out) > MIN_CONTRAST_RATIO * l_contrast(glow)


def test_sepia_with_scan_noise_still_keeps_its_tone() -> None:
    noisy = make_faded_sepia(height=900, width=1200, noise=2)
    _assert_tone_kept(noisy, restore_colour(noisy, DPI))


@pytest.mark.parametrize("fraction", INK_FRACTIONS)
def test_sepia_with_a_little_coloured_ink_is_still_a_tone(fraction: float) -> None:
    inked = make_sepia_with_ink(fraction)
    out = restore_colour(inked, DPI)
    _assert_tone_kept(inked, out)
    assert l_contrast(out) > MIN_CONTRAST_RATIO * l_contrast(inked)


@pytest.mark.parametrize("tint", [(6.0, 0.0, -5.0), (8.0, 3.0, -8.0), (-4.0, 0.0, 5.0)])
def test_black_and_white_on_tinted_paper_does_not_amplify_the_tint(
    tint: tuple[float, float, float],
) -> None:
    print_ = make_tinted_black_and_white(tint)
    out = restore_colour(print_, DPI)
    assert paper_chroma(out) <= TINT_MAX_GROWTH * paper_chroma(print_)
    assert l_contrast(out) > MIN_CONTRAST_RATIO * l_contrast(print_)


def test_near_white_page_keeps_its_paper_level() -> None:
    page = make_near_white_page()
    out = restore_colour(page, DPI)
    assert abs(paper_level(out) - paper_level(page)) <= PAPER_MAX_CHANGE


@pytest.mark.parametrize("kind", ["lawn", "skin", "sea"])
def test_one_hue_scene_keeps_at_least_half_of_its_colour(kind: str) -> None:
    scene = make_dominant_hue(kind)
    out = restore_colour(scene, DPI)
    assert mean_chroma(out) >= SCENE_MIN_CHROMA_KEPT * mean_chroma(scene)


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
    settings = RestoreSettings(saturation_gain=1.3)
    unboosted = dataclasses.replace(settings, saturation_gain=1.0)  # same stretch, no recovery
    natural = make_natural()
    ratios = []
    for keep in (0.6, 0.35, 0.15):  # mean chroma about 10.7, 6.2 and 2.7
        dull = desaturate(natural, keep)
        ratios.append(
            mean_chroma(restore_colour(dull, DPI, settings))
            / mean_chroma(restore_colour(dull, DPI, unboosted))
        )
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
