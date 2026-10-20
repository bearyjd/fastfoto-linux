"""Shared generated builders for the photo geometry tests."""

import numpy as np

from fastfoto_linux.photo_edits import (
    EyeEdit,
    PhotoEditRecipe,
    PhotoGeometry,
    PhotoSource,
    PhotoTone,
    update_geometry,
    update_tone,
)

GRID = np.array([[1, 2, 3], [4, 5, 6]], dtype=np.uint8)
GRID_RGB = np.stack([GRID, GRID + 10, GRID + 20], axis=-1)
TONE = PhotoTone(brightness=25, contrast=-35, saturation=60, strength=75)


def geometry_recipe(
    source: PhotoSource,
    geometry: PhotoGeometry,
    *,
    eyes: tuple[EyeEdit, ...] = (),
    tone: PhotoTone | None = None,
) -> PhotoEditRecipe:
    recipe = PhotoEditRecipe(source, eyes)
    if tone is not None:
        recipe = update_tone(recipe, tone)
    return update_geometry(recipe, geometry)
