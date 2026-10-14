"""A scene that is mostly one hue is not a colour cast: hue and chroma stay.

Sand, an amber sunset, a close-up of skin and a lawn all look like a print with a cast to a
channel balance that is not told otherwise: it turns amber to lemon and cream to white. Channels
are balanced against each other only when the print's own neutrals show a cast.
"""

import numpy as np
import pytest

from fastfoto_linux.enhance.restore import RestoreSettings, restore_colour
from tests._restore_scenes import WARM_SCENES, colour_change, make_warm_scene
from tests._restore_synth import DPI, FULL_SCALE, l_contrast, make_reference

MAX_HUE_SHIFT_DEG = 10.0
CHROMA_BAND = (0.8, 1.2)  # kept, neither stripped nor amplified
NO_BALANCE = RestoreSettings(saturation_gain=1.0)


@pytest.mark.parametrize("kind", list(WARM_SCENES))
def test_a_one_hue_scene_without_a_cast_keeps_its_hue_and_chroma(kind: str) -> None:
    scene = make_warm_scene(kind)
    out = restore_colour(scene, DPI)
    hue_shift, chroma_ratio = colour_change(scene, out)
    assert hue_shift <= MAX_HUE_SHIFT_DEG
    assert CHROMA_BAND[0] <= chroma_ratio <= CHROMA_BAND[1]
    assert l_contrast(out) >= l_contrast(scene)


def _squeezed(**channels: tuple[float, float]) -> np.ndarray:
    """The test card with the named channels (r, g, b) squeezed into (low, high)."""
    img = make_reference()
    for name, (low, high) in channels.items():
        channel = "rgb".index(name)
        img[..., channel] = np.rint(low + img[..., channel] / FULL_SCALE * (high - low))
    return img


IMBALANCED = {
    "red squeezed": _squeezed(r=(100, 140)),
    "green lifted": _squeezed(g=(40, 200)),
    "red squeezed, green narrowed": _squeezed(r=(100, 140), g=(30, 230)),
}


@pytest.mark.parametrize("img", IMBALANCED.values(), ids=IMBALANCED.keys())
def test_without_cast_evidence_every_pixel_keeps_its_colour_offsets(img: np.ndarray) -> None:
    """Squeezing one channel leaves nothing that balancing could turn neutral: no evidence."""
    out = restore_colour(img, DPI, NO_BALANCE)
    delta = out.astype(np.int16) - img.astype(np.int16)
    free = ((img > 0) & (img < FULL_SCALE) & (out > 0) & (out < FULL_SCALE)).all(axis=-1)
    assert free.mean() > 0.1  # enough pixels away from the clipping to read
    assert np.any(delta[free])  # the print is still stretched ...
    assert np.ptp(delta[free], axis=1).max() == 0  # ... by the same amount in every channel
