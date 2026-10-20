"""Generated sources and recipes for the straighten tests."""

from dataclasses import replace
from pathlib import Path

import numpy as np

from fastfoto_linux.photo_edits import (
    PhotoEditRecipe,
    PhotoGeometry,
    PhotoSource,
    PhotoTone,
    update_geometry,
    update_tone,
)
from tests.photo_edits.helpers import source_at

TONE = PhotoTone(brightness=20, contrast=-10, saturation=30, strength=80)


def noise(height: int, width: int, seed: int = 1) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, 256, (height, width, 3), dtype=np.uint8)


def sized_source(tmp_path: Path, height: int, width: int, *, dpi: float = 300.0) -> PhotoSource:
    """The helper source with different generated pixels (identity hash is not re-derived)."""
    base = source_at(tmp_path)
    return replace(
        base,
        width=width,
        height=height,
        dpi_x=dpi,
        dpi_y=dpi,
        effective_dpi=dpi,
        pixels=noise(height, width),
    )


def straight_recipe(
    source: PhotoSource, geometry: PhotoGeometry, *, tone: PhotoTone | None = None, eyes=()
) -> PhotoEditRecipe:
    recipe = PhotoEditRecipe(source, eyes)
    if tone is not None:
        recipe = update_tone(recipe, tone)
    return update_geometry(recipe, geometry)
