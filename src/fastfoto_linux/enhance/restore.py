"""Colour restoration for faded, colour-cast prints (stub: implemented in the green commit)."""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class RestoreSettings:
    """Tunable knobs for :func:`restore_colour`."""

    low_clip_pct: float = 0.5
    high_clip_pct: float = 0.5
    max_gain: float = 3.0
    saturation_gain: float = 1.15
    clahe: bool = False


DEFAULT = RestoreSettings()


def restore_colour(img: np.ndarray, dpi: float, settings: RestoreSettings = DEFAULT) -> np.ndarray:
    raise NotImplementedError


def measure_cast(img: np.ndarray) -> tuple[float, float]:
    raise NotImplementedError
