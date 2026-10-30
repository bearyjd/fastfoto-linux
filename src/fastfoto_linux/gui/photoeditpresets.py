"""Editor-only colour presets: absolute tone and white balance values, never stored in a recipe.

The values are starting points chosen by reasoning on synthetic data, not calibrated on scans.
"""

from dataclasses import dataclass

from fastfoto_linux.photo_edits import PhotoEditRecipe, PhotoTone, PhotoWhiteBalance

UNKNOWN_PRESET = "Choose a listed preset."


@dataclass(frozen=True)
class Preset:
    id: str
    label: str
    tone: PhotoTone
    white_balance: PhotoWhiteBalance


PRESETS = (
    Preset("warm", "Warm", PhotoTone(), PhotoWhiteBalance(25, 0)),
    Preset("cool", "Cool", PhotoTone(), PhotoWhiteBalance(-25, 0)),
    Preset("faded", "Faded print", PhotoTone(0, 15, 25, 100), PhotoWhiteBalance(-10, -10)),
    Preset("mono", "Black and white", PhotoTone(0, 10, -100, 100), PhotoWhiteBalance()),
)


def preset(preset_id: str) -> Preset:
    for item in PRESETS:
        if item.id == preset_id:
            return item
    raise ValueError(UNKNOWN_PRESET)


def matching_preset(recipe: PhotoEditRecipe | None) -> str:
    """The id of the preset whose values the draft equals, else ``""``."""
    if recipe is None:
        return ""
    for item in PRESETS:
        if recipe.tone == item.tone and recipe.white_balance == item.white_balance:
            return item.id
    return ""
