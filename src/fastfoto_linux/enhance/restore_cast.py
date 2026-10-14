"""Colour statistics that decide how a print is restored: is it a single tone, does it carry a cast.

Everything here works on a block-averaged copy of the photo (about ``STAT_MAX_PIXELS`` pixels):
averaging removes scan noise, and the statistics need no more than that.
"""

import math

import cv2
import numpy as np

RGB_CHANNELS = 3
LAB_NEUTRAL = 128.0  # 8-bit OpenCV LAB stores a* and b* offset by this value
STAT_MAX_PIXELS = 250_000  # colour statistics use a block-averaged copy of about this size
NEUTRAL_MEAN_CHROMA = 3.0  # mean LAB chroma below this: a black-and-white print
TRIM_PCT = 5.0  # percent trimmed from each end of a spread measurement (a few % of ink)
NO_DIRECTION_LENGTH = 1e-6  # a mean colour this short has no direction
TONE_MAX_HUE_SCATTER = 0.55  # trimmed std of a*, b* across the mean colour's direction
NEUTRAL_AFTER_BALANCE_CHROMA = 6.0  # chroma below this after balancing: "should be neutral"
MIN_NEUTRAL_FRACTION = 0.02  # fewer neutral-after-balance pixels than this: no evidence at all
CAST_EVIDENCE_CHROMA = 10.0  # neutrals this far from neutral in the print: a cast, not a scene


def block_average(img: np.ndarray) -> np.ndarray:
    """RGB copy of about ``STAT_MAX_PIXELS`` pixels, each the mean of a block of the original."""
    height, width = img.shape[:2]
    scale = min(1.0, math.sqrt(STAT_MAX_PIXELS / (height * width)))
    if scale < 1.0:
        size = (max(1, round(width * scale)), max(1, round(height * scale)))
        img = cv2.resize(img, size, interpolation=cv2.INTER_AREA)
    return np.ascontiguousarray(img)


def ab_offsets(rgb: np.ndarray) -> np.ndarray:
    """CIE a*, b* of an RGB ``uint8`` image as offsets (N, 2) from neutral."""
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
    return lab[..., 1:].reshape(-1, 2).astype(np.float32) - LAB_NEUTRAL


def sample_ab(img: np.ndarray) -> np.ndarray:
    """a*, b* offsets (N, 2) of a block-averaged copy of ``img``."""
    return ab_offsets(block_average(img))


def mean_chroma(ab: np.ndarray) -> float:
    return float(np.hypot(ab[:, 0], ab[:, 1]).mean())


def _trimmed_std(values: np.ndarray) -> float:
    """Std after dropping the most extreme ``TRIM_PCT`` percent at each end (a little ink)."""
    low, high = np.percentile(values, [TRIM_PCT, 100.0 - TRIM_PCT])
    return float(values[(values >= low) & (values <= high)].std())


def hue_scatter(ab: np.ndarray) -> float:
    """Spread of a*, b* across the direction of the mean colour (all directions if neutral).

    Variation along the mean colour's direction is only chroma changing with lightness, as in
    sepia; variation across it is a different colour. A trimmed std ignores a few percent of
    outliers (ink) but, unlike a median-based spread, not a large coloured part of the scene.
    """
    center = ab.mean(axis=0)
    deviation = ab - center
    length = float(np.hypot(*center))
    if length < NO_DIRECTION_LENGTH:
        return math.hypot(_trimmed_std(deviation[:, 0]), _trimmed_std(deviation[:, 1]))
    return _trimmed_std(deviation @ np.array([-center[1], center[0]]) / length)


def is_single_tone(ab: np.ndarray) -> bool:
    """True for black and white, sepia and other prints whose colour is a single tone."""
    return mean_chroma(ab) < NEUTRAL_MEAN_CHROMA or hue_scatter(ab) < TONE_MAX_HUE_SCATTER


def cast_evidence(ab: np.ndarray, balanced_ab: np.ndarray) -> float:
    """How far from neutral the print's own neutrals are; 0 if it has none.

    ``ab`` is the print's a*, b* and ``balanced_ab`` those of the same pixels after a
    provisional per-channel balance. Pixels that balancing turns neutral are the ones a cast
    would have tinted: the evidence is their mean colour offset in the print. A scene that merely
    has one dominant colour has no such pixels, or they are already neutral in the print.
    """
    near = np.hypot(balanced_ab[:, 0], balanced_ab[:, 1]) < NEUTRAL_AFTER_BALANCE_CHROMA
    if near.mean() < MIN_NEUTRAL_FRACTION:
        return 0.0
    return float(np.hypot(*ab[near].mean(axis=0)))
