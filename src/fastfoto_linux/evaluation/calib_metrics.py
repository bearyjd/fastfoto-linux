"""Pure numpy measurements for the calibration harness: colour error, noise, edges, skew.

Nothing here reads a file or knows about the corpus; every function takes arrays and boxes
``(x, y, width, height)`` and returns numbers (or None when the input cannot be measured).
"""

import math
from collections.abc import Sequence

import cv2
import numpy as np

from fastfoto_linux.evaluation.calib_annotations import Box
from fastfoto_linux.evaluation.stats import proportion
from fastfoto_linux.photo_edits.detail import GRAY_WEIGHTS

DECIMALS = 4
FULL_SCALE = 255.0
MIN_EDGE_RANGE = 1.0  # levels: below this a box has no edge to measure
TENTHS_PER_DEGREE = 10
LOW_FRACTION = 0.1
HIGH_FRACTION = 0.9
PERCENT = 100.0
_POW7 = 25.0**7
HALF_TURN = 180.0
TURN = 360.0
_PROPORTION_KEYS = ("k", "n", "p", "lo", "hi", "zero_upper_bound")


def _hue(b: np.ndarray, a_prime: np.ndarray) -> np.ndarray:
    return np.degrees(np.arctan2(b, a_prime)) % TURN


def _hue_difference(h1: np.ndarray, h2: np.ndarray, chroma_product: np.ndarray) -> np.ndarray:
    diff = h2 - h1
    diff = np.where(diff > HALF_TURN, diff - TURN, np.where(diff < -HALF_TURN, diff + TURN, diff))
    return np.where(chroma_product == 0, 0.0, diff)


def _mean_hue(h1: np.ndarray, h2: np.ndarray, chroma_product: np.ndarray) -> np.ndarray:
    total = h1 + h2
    wrapped = np.where(total < TURN, total + TURN, total - TURN) / 2
    mean = np.where(np.abs(h1 - h2) <= HALF_TURN, total / 2, wrapped)
    return np.where(chroma_product == 0, total, mean)


def ciede2000(lab1: np.ndarray, lab2: np.ndarray) -> np.ndarray:
    """CIEDE2000 between Lab colours (``...x3`` arrays, kLCH = 1), after Sharma, Wu and Dalal."""
    l1, a1, b1 = (lab1[..., i].astype(np.float64) for i in range(3))
    l2, a2, b2 = (lab2[..., i].astype(np.float64) for i in range(3))
    c_mean = (np.hypot(a1, b1) + np.hypot(a2, b2)) / 2
    g = 0.5 * (1 - np.sqrt(c_mean**7 / (c_mean**7 + _POW7)))
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1p, c2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1p, h2p = _hue(b1, a1p), _hue(b2, a2p)
    product = c1p * c2p
    d_h = 2 * np.sqrt(product) * np.sin(np.radians(_hue_difference(h1p, h2p, product)) / 2)
    l_bar, c_bar = (l1 + l2) / 2, (c1p + c2p) / 2
    h_bar = np.radians(_mean_hue(h1p, h2p, product))
    t = (
        1
        - 0.17 * np.cos(h_bar - np.radians(30))
        + 0.24 * np.cos(2 * h_bar)
        + 0.32 * np.cos(3 * h_bar + np.radians(6))
        - 0.20 * np.cos(4 * h_bar - np.radians(63))
    )
    theta = np.radians(30) * np.exp(-(((np.degrees(h_bar) - 275) / 25) ** 2))
    r_c = 2 * np.sqrt(c_bar**7 / (c_bar**7 + _POW7))
    s_l = 1 + 0.015 * (l_bar - 50) ** 2 / np.sqrt(20 + (l_bar - 50) ** 2)
    term_l = (l2 - l1) / s_l
    term_c = (c2p - c1p) / (1 + 0.045 * c_bar)
    term_h = d_h / (1 + 0.015 * c_bar * t)
    return np.sqrt(term_l**2 + term_c**2 + term_h**2 - np.sin(2 * theta) * r_c * term_c * term_h)


def _crop(array: np.ndarray, box: Box) -> np.ndarray:
    x, y, width, height = box
    return array[y : y + height, x : x + width]


def neutral_de00(rgb: np.ndarray, boxes: Sequence[Box]) -> float:
    """Mean over ``boxes`` of the CIEDE2000 between the box's mean colour and the neutral of
    the same lightness (a* = b* = 0): 0 for a patch that is exactly grey."""
    errors = []
    for box in boxes:
        patch = np.ascontiguousarray(_crop(rgb, box), dtype=np.float32) / FULL_SCALE
        mean = cv2.cvtColor(patch, cv2.COLOR_RGB2LAB).reshape(-1, 3).mean(axis=0)
        errors.append(float(ciede2000(mean, np.array([mean[0], 0.0, 0.0]))))
    return sum(errors) / len(errors)


def luma(rgb: np.ndarray) -> np.ndarray:
    """Rec. 709 luma of an RGB image on the 0 to 255 scale, as float64."""
    weights = np.array(GRAY_WEIGHTS, dtype=np.float64)
    return rgb.astype(np.float64) @ weights


def flat_sigmas(grey: np.ndarray, boxes: Sequence[Box]) -> list[float]:
    """The standard deviation of ``grey`` inside each box."""
    return [float(np.std(_crop(grey, box))) for box in boxes]


def _profile(grey: np.ndarray, box: Box, axis: str) -> np.ndarray:
    """The mean level along the axis the edge is crossed on ("h": along x, "v": along y)."""
    return _crop(grey, box).mean(axis=0 if axis == "h" else 1)


def _crossing(profile: np.ndarray, level: float, first: int) -> float | None:
    hits = np.flatnonzero(profile[first:] >= level)
    if not hits.size:
        return None
    index = first + int(hits[0])
    if index == 0:
        return 0.0
    below = float(profile[index - 1])
    return index - 1 + (level - below) / (float(profile[index]) - below)


def edge_width(grey: np.ndarray, box: Box, axis: str) -> float | None:
    """The 10 to 90 percent rise distance, in pixels, of the edge in ``box``; None for no edge."""
    profile = _profile(grey, box, axis)
    low, high = float(profile.min()), float(profile.max())
    if high - low < MIN_EDGE_RANGE:
        return None
    if profile[0] > profile[-1]:
        profile = profile[::-1]
    start = _crossing(profile, low + LOW_FRACTION * (high - low), 0)
    if start is None:
        return None
    end = _crossing(profile, low + HIGH_FRACTION * (high - low), int(start))
    return None if end is None else end - start


def halo_pct(before: np.ndarray, after: np.ndarray, box: Box, axis: str) -> float | None:
    """The overshoot of ``after`` past the levels either side of the edge in ``before``, as a
    percentage of the edge height; None for no edge."""
    reference = _profile(before, box, axis)
    low, high = float(reference.min()), float(reference.max())
    if high - low < MIN_EDGE_RANGE:
        return None
    changed = _profile(after, box, axis)
    overshoot = max(float(changed.max()) - high, low - float(changed.min()), 0.0)
    return PERCENT * overshoot / (high - low)


def skew_error_deg(estimate_tenths: int, correction_tenths: Sequence[int]) -> float:
    """``|estimate - mean annotation|`` in degrees (both clockwise corrections, in tenths)."""
    truth = sum(correction_tenths) / len(correction_tenths)
    return abs(estimate_tenths - truth) / TENTHS_PER_DEGREE


def wrong_direction(estimate_tenths: int, correction_tenths: Sequence[int]) -> bool:
    """The estimate turns the page the opposite way to the mean annotation (0 has no way)."""
    return estimate_tenths * sum(correction_tenths) < 0


def rounded(value: object) -> object:
    """``value`` with every float rounded to ``DECIMALS`` places (and -0.0 made 0.0)."""
    if isinstance(value, dict):
        return {key: rounded(inner) for key, inner in value.items()}
    if isinstance(value, (list, tuple)):
        return [rounded(inner) for inner in value]
    if type(value) is float and math.isfinite(value):
        return round(value, DECIMALS) + 0.0
    return value


def proportion_entry(k: int, n: int) -> dict[str, object]:
    """``stats.proportion`` without its free-text note (a report holds no free text)."""
    full = proportion(k, n)
    return {key: full[key] for key in _PROPORTION_KEYS}
