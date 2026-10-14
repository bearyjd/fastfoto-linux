"""A faded colour print with a cast is de-cast: whatever the scene chroma or brightness.

A constant cast shifts the mean colour but leaves the scene's colour scatter, so it must never be
mistaken for a monochrome "tone" (sepia, black and white) that is to be kept.
"""

import pytest

from fastfoto_linux.enhance.restore import restore_colour
from tests._restore_synth import (
    BLUE_VIOLET_CAST,
    DPI,
    FADE_HIGH,
    FADE_LOW,
    RED_CAST,
    fade_between,
    make_cast_card,
    ramp_cast,
)

MIN_CAST_BEFORE = 15.0  # sanity: the fixture really carries a strong cast
CAST_REDUCTION = 0.5
CASTS = {
    "red": RED_CAST,
    "blue-violet": BLUE_VIOLET_CAST,
    "magenta": (FADE_LOW, FADE_HIGH),
}


@pytest.mark.parametrize("scene_chroma", [6.0, 12.0, 25.0])
@pytest.mark.parametrize("cast", CASTS.values(), ids=CASTS.keys())
def test_strong_cast_is_removed_whatever_the_scene_chroma(
    cast: tuple[tuple[float, ...], tuple[float, ...]], scene_chroma: float
) -> None:
    faded = fade_between(make_cast_card(scene_chroma), *cast)
    assert ramp_cast(faded) > MIN_CAST_BEFORE
    assert ramp_cast(restore_colour(faded, DPI)) <= CAST_REDUCTION * ramp_cast(faded)


@pytest.mark.parametrize(("scene_chroma", "scale"), [(12.0, 0.7), (12.0, 0.5), (6.0, 0.5)])
@pytest.mark.parametrize("cast", CASTS.values(), ids=CASTS.keys())
def test_dark_faded_print_with_a_cast_is_de_cast(
    cast: tuple[tuple[float, ...], tuple[float, ...]], scene_chroma: float, scale: float
) -> None:
    faded = fade_between(make_cast_card(scene_chroma, scale), *cast)
    assert ramp_cast(faded) > MIN_CAST_BEFORE
    assert ramp_cast(restore_colour(faded, DPI)) <= CAST_REDUCTION * ramp_cast(faded)
