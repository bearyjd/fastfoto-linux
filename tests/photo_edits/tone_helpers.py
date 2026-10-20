"""Small independent scalar reference and generated RGB-only tone sources."""

import math
from dataclasses import replace
from pathlib import Path

import numpy as np

from fastfoto_linux.photo_edits import PhotoSource, PhotoTone
from tests.photo_edits.helpers import source_at


def tone_source(folder: Path, pixels: np.ndarray) -> PhotoSource:
    return replace(source_at(folder), pixels=pixels, width=pixels.shape[1], height=pixels.shape[0])


def reference_tone(pixels: np.ndarray, tone: PhotoTone) -> np.ndarray:
    """Scalar contract oracle; no production renderer or vectorized implementation."""
    result = np.empty_like(pixels)
    for coordinate in np.ndindex(pixels.shape[:2]):
        original = [int(channel) / 255 for channel in pixels[coordinate]]
        adjusted = [
            (channel + tone.brightness / 200 - 0.5) * (1 + tone.contrast / 100) + 0.5
            for channel in original
        ]
        gray = 0.2126 * adjusted[0] + 0.7152 * adjusted[1] + 0.0722 * adjusted[2]
        for channel in range(3):
            saturated = gray + (adjusted[channel] - gray) * (1 + tone.saturation / 100)
            mixed = original[channel] + tone.strength / 100 * (saturated - original[channel])
            result[(*coordinate, channel)] = math.floor(255 * min(1, max(0, mixed)) + 0.5)
    return result
