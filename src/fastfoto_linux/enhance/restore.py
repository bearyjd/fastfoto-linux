"""Colour restoration for faded, colour-cast prints.

Deterministic and classic (no machine learning), in three stages:

1. *Simplest Color Balance* (Limare, Lisani, Morel, Petro, Sbert, IPOL 2011): clip a small
   percentile of every channel at both ends and stretch what is left to the full scale. This
   removes the cast and restores contrast. Percentiles are exact, from full-resolution 256-bin
   histograms, so the clipped fraction is what the settings say at any resolution.
2. Gentle saturation recovery on LAB chroma, scaled by how desaturated the image measurably is.
3. Optional mild local contrast (CLAHE on lightness), off by default.

Safeguards keep unusual images from being damaged:

* Run this on the cropped photo. Pixels that are pure black or pure white in all three channels
  (a scanner border or background) are ignored when measuring, so a frame cannot pin the
  percentiles; the frame itself is left untouched.
* A channel that already spans nearly the full scale, or is flat, is left alone, and the
  per-channel gain is capped.
* A monochrome tone (sepia, black and white) or a single dominant hue (a sunset) is stretched
  with ONE shared curve, so the tone is kept instead of being neutralised channel by channel.
* The black point never moves so far that the median would fall below a fixed fraction of the
  scale, so low-key scenes (night shots) are not crushed.

The input array is never modified.
"""

import logging
import math
from dataclasses import dataclass

import cv2
import numpy as np

_LOG = logging.getLogger(__name__)

MM_PER_INCH = 25.4
FULL_SCALE = 255
LUT_SIZE = FULL_SCALE + 1
RGB_NDIM = 3
RGB_CHANNELS = 3
LAB_NEUTRAL = 128.0  # 8-bit OpenCV LAB stores a* and b* offset by this value

MAX_CLIP_PCT = 50.0  # each tail must stay below the median
MAX_SATURATION_GAIN = 3.0
SKIP_RANGE_FRACTION = 0.95  # a channel spanning this much of the scale needs no stretch
MIN_RANGE_LEVELS = 8  # a channel narrower than this is flat: stretching it would be noise
MIN_OUTPUT_MEDIAN_FRACTION = 0.2  # the stretch may not push the median below this of the scale
STAT_MAX_PIXELS = 1_000_000  # colour statistics use a strided sample of about this many pixels
NEUTRAL_MEAN_CHROMA = 3.0  # mean LAB chroma below this: a black-and-white print
SINGLE_HUE_CONCENTRATION = 0.9  # |mean (a*, b*)| / mean chroma at or above this: one hue
SHARED_MIN_SPAN_FRACTION = 0.6  # shared stretch only if tonal range, not channel offsets, dominates
DESATURATED_MEAN_CHROMA = 10.0  # saturation recovery fades out as mean chroma reaches this
CLAHE_CLIP_LIMIT = 1.5  # subtle: close to plain histogram equalisation's lower bound
CLAHE_TILE_MM = 25.0
CLAHE_MIN_TILES = 2


@dataclass(frozen=True)
class RestoreSettings:
    """Tunable knobs for :func:`restore_colour`.

    ``low_clip_pct`` / ``high_clip_pct``: percent of pixels clipped at each end of every channel
    before stretching. ``max_gain``: cap on the per-channel contrast gain. ``saturation_gain``:
    chroma multiplier reached by a fully desaturated image (1.0 disables recovery; images with
    mean chroma of ``DESATURATED_MEAN_CHROMA`` or more are never boosted). ``clahe``: add mild
    local contrast on lightness.
    """

    low_clip_pct: float = 0.5
    high_clip_pct: float = 0.5
    max_gain: float = 2.0
    saturation_gain: float = 1.15
    clahe: bool = False

    def __post_init__(self) -> None:
        for name in ("low_clip_pct", "high_clip_pct"):
            value = getattr(self, name)
            if not (math.isfinite(value) and 0.0 <= value < MAX_CLIP_PCT):
                raise ValueError(
                    f"{name} must be a finite number in [0, {MAX_CLIP_PCT}), got {value}"
                )
        if not (math.isfinite(self.max_gain) and self.max_gain >= 1.0):
            raise ValueError(f"max_gain must be a finite number >= 1, got {self.max_gain}")
        if not (
            math.isfinite(self.saturation_gain)
            and 1.0 <= self.saturation_gain <= MAX_SATURATION_GAIN
        ):
            raise ValueError(
                f"saturation_gain must be a finite number in [1, {MAX_SATURATION_GAIN}], "
                f"got {self.saturation_gain}"
            )


DEFAULT = RestoreSettings()


def restore_colour(img: np.ndarray, dpi: float, settings: RestoreSettings = DEFAULT) -> np.ndarray:
    """Return a colour-restored copy of an RGB ``uint8`` photo scanned at ``dpi``.

    Compatible with the pipeline's ``Enhancer`` signature ``(img, dpi) -> img``. ``dpi`` only
    sizes the optional local-contrast tiles: the colour correction is resolution independent.
    """
    _require_rgb_uint8(img)
    if not (math.isfinite(dpi) and dpi > 0):
        raise ValueError(f"dpi must be a positive finite number, got {dpi}")
    out = _stretch_channels(img, settings)
    out = _recover_saturation(out, settings.saturation_gain)
    if settings.clahe:
        out = _local_contrast(out, dpi)
    return out


def measure_cast(img: np.ndarray) -> tuple[float, float]:
    """Mean CIE a* and b* of an RGB ``uint8`` image: 0, 0 is neutral, ``a* > 0`` is magenta/red."""
    _require_rgb_uint8(img)
    lab = cv2.cvtColor(img.astype(np.float32) / FULL_SCALE, cv2.COLOR_RGB2LAB)
    return float(lab[..., 1].mean()), float(lab[..., 2].mean())


def _require_rgb_uint8(img: np.ndarray) -> None:
    valid = img.dtype == np.uint8 and img.ndim == RGB_NDIM and img.shape[-1] == RGB_CHANNELS
    if not valid or not img.size:
        raise ValueError(
            "expected a non-empty uint8 RGB image of shape (H, W, 3), "
            f"got dtype={img.dtype} shape={img.shape}"
        )


def _mm_to_px(mm: float, dpi: float) -> int:
    return round(mm * dpi / MM_PER_INCH)


def _flat_mask(img: np.ndarray, level: int) -> np.ndarray:
    """255 where all three channels of a pixel equal ``level``."""
    return cv2.inRange(img, (level,) * RGB_CHANNELS, (level,) * RGB_CHANNELS)


def _frame_mask(img: np.ndarray) -> np.ndarray:
    """255 where a pixel is pure black or pure white in all channels (scanner border)."""
    return _flat_mask(img, 0) | _flat_mask(img, FULL_SCALE)


def _histograms(img: np.ndarray) -> np.ndarray:
    """Exact per-channel 256-bin histograms of the pixels outside the pure black/white frame."""
    hists = np.stack(
        [np.bincount(img[..., c].ravel(), minlength=LUT_SIZE) for c in range(RGB_CHANNELS)]
    )
    for level in (0, FULL_SCALE):
        hists[:, level] -= np.count_nonzero(_flat_mask(img, level))
    return hists


def _channel_bounds(hist: np.ndarray, settings: RestoreSettings) -> tuple[float, float] | None:
    """Black and white points of one channel, or ``None`` if it has no measurable pixels.

    At most ``low_clip_pct`` / ``high_clip_pct`` of the pixels end up at or beyond them, and the
    black point is held back for low-key images (see ``MIN_OUTPUT_MEDIAN_FRACTION``).
    """
    total = int(hist.sum())
    if total == 0:
        return None
    cdf = np.cumsum(hist)
    low = max(int(np.searchsorted(cdf, total * settings.low_clip_pct / 100.0, "right")) - 1, 0)
    reach = total * (1.0 - settings.high_clip_pct / 100.0)
    high = min(int(np.searchsorted(cdf, reach, "left")) + 1, FULL_SCALE)
    median = int(np.searchsorted(cdf, total / 2.0, "left"))
    ceiling = (median - MIN_OUTPUT_MEDIAN_FRACTION * high) / (1.0 - MIN_OUTPUT_MEDIAN_FRACTION)
    return float(min(low, max(ceiling, 0.0))), float(high)


def _channel_lut(low: float, high: float, max_gain: float) -> np.ndarray:
    """Lookup table stretching ``[low, high]`` to the full scale, or the identity if unneeded."""
    levels = np.arange(LUT_SIZE, dtype=np.float32)
    span = high - low
    if span < MIN_RANGE_LEVELS or span >= SKIP_RANGE_FRACTION * FULL_SCALE:
        return levels.astype(np.uint8)
    full_gain = FULL_SCALE / span
    values = (levels - low) * full_gain
    if full_gain > max_gain:  # blend with the identity so the gain is exactly max_gain
        weight = (max_gain - 1.0) / (full_gain - 1.0)
        values = (1.0 - weight) * levels + weight * values
    return np.clip(np.rint(values), 0, FULL_SCALE).astype(np.uint8)


def _sample_ab(img: np.ndarray) -> np.ndarray:
    """LAB a*, b* offsets (N, 2) of a strided sample, frame pixels excluded."""
    step = max(1, math.ceil(math.sqrt(img.shape[0] * img.shape[1] / STAT_MAX_PIXELS)))
    sample = np.ascontiguousarray(img[::step, ::step])
    lab = cv2.cvtColor(sample, cv2.COLOR_RGB2LAB)
    return lab[_frame_mask(sample) == 0][:, 1:].astype(np.float32) - LAB_NEUTRAL


def _mean_chroma(ab: np.ndarray) -> float:
    return float(np.hypot(ab[:, 0], ab[:, 1]).mean()) if len(ab) else 0.0


def _is_single_tone(img: np.ndarray) -> bool:
    """True for black and white, sepia and other prints whose colour is one hue family."""
    ab = _sample_ab(img)
    chroma = _mean_chroma(ab)
    if chroma < NEUTRAL_MEAN_CHROMA:
        return True
    return float(np.hypot(*ab.mean(axis=0))) / chroma >= SINGLE_HUE_CONCENTRATION


def _shared_bounds(bounds: list[tuple[float, float]]) -> tuple[float, float] | None:
    """One black/white point for all channels, or ``None`` if channel offsets dominate.

    A flat coloured image has tiny tonal range in every channel but large differences between
    channels; a shared stretch would read those differences as range and wreck the colour.
    """
    low = min(lo for lo, _ in bounds)
    high = max(hi for _, hi in bounds)
    widest = max(hi - lo for lo, hi in bounds)
    return (low, high) if widest >= SHARED_MIN_SPAN_FRACTION * (high - low) else None


def _stretch_luts(img: np.ndarray, settings: RestoreSettings) -> list[np.ndarray]:
    bounds = [_channel_bounds(h, settings) for h in _histograms(img)]
    if any(b is None for b in bounds):  # nothing but frame: nothing to measure
        return [_channel_lut(0.0, 0.0, settings.max_gain)] * RGB_CHANNELS
    _LOG.debug("restore: channel bounds %s", bounds)
    shared = _shared_bounds(bounds) if _is_single_tone(img) else None
    if shared is not None:
        return [_channel_lut(*shared, settings.max_gain)] * RGB_CHANNELS
    return [_channel_lut(lo, hi, settings.max_gain) for lo, hi in bounds]


def _stretch_channels(img: np.ndarray, settings: RestoreSettings) -> np.ndarray:
    luts = np.stack(_stretch_luts(img, settings), axis=-1)
    return cv2.LUT(img, luts.reshape(LUT_SIZE, 1, RGB_CHANNELS))


def _recover_saturation(img: np.ndarray, gain: float) -> np.ndarray:
    """Scale LAB chroma up in proportion to the measured desaturation; neutrals stay neutral."""
    if gain == 1.0:
        return img
    deficit = 1.0 - _mean_chroma(_sample_ab(img)) / DESATURATED_MEAN_CHROMA
    if deficit <= 0.0:
        return img
    scale = 1.0 + (gain - 1.0) * deficit
    lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)
    chroma = lab[..., 1:].astype(np.float32) - LAB_NEUTRAL
    boosted = lab.copy()
    boosted[..., 1:] = np.clip(np.rint(chroma * scale + LAB_NEUTRAL), 0, FULL_SCALE).astype(
        np.uint8
    )
    # Apply only the change the boost makes, so the 8-bit LAB round trip adds no error.
    delta = cv2.cvtColor(boosted, cv2.COLOR_LAB2RGB).astype(np.int16)
    delta -= cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)
    return np.clip(img.astype(np.int16) + delta, 0, FULL_SCALE).astype(np.uint8)


def _local_contrast(img: np.ndarray, dpi: float) -> np.ndarray:
    lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)
    height, width = lab.shape[:2]
    tile_px = max(1, _mm_to_px(CLAHE_TILE_MM, dpi))
    grid = (
        max(CLAHE_MIN_TILES, round(width / tile_px)),
        max(CLAHE_MIN_TILES, round(height / tile_px)),
    )
    clahe = cv2.createCLAHE(clipLimit=CLAHE_CLIP_LIMIT, tileGridSize=grid)
    lab[..., 0] = clahe.apply(lab[..., 0])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)
