"""Colour restoration for faded, colour-cast prints.

Deterministic and classic (no machine learning), in three stages:

1. *Simplest Color Balance* (Limare, Lisani, Morel, Petro, Sbert, IPOL 2011): clip a small
   percentile of every channel at both ends and stretch what is left to the full scale. This
   removes the cast and restores contrast. Percentiles are measured on a downsampled copy; the
   stretch is applied to the full-resolution image through a lookup table.
2. Gentle saturation recovery on LAB chroma, only when the image is measurably desaturated.
3. Optional mild local contrast (CLAHE on lightness), off by default.

Safeguards keep already well-balanced photos almost untouched: a channel that already spans
nearly the full scale, or that is flat, is left alone, and the per-channel gain is capped.
The input array is never modified.
"""

import logging
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

ANALYSIS_DPI = 150.0  # percentiles are measured at no more than this resolution
MAX_CLIP_PCT = 50.0  # each tail must stay below the median
SKIP_RANGE_FRACTION = 0.95  # a channel spanning this much of the scale needs no stretch
MIN_RANGE_LEVELS = 8  # a channel narrower than this is flat: stretching it would be noise
DESATURATED_MEAN_CHROMA = 20.0  # mean LAB chroma below this counts as desaturated
CLAHE_CLIP_LIMIT = 1.5  # subtle: close to plain histogram equalisation's lower bound
CLAHE_TILE_MM = 25.0
CLAHE_MIN_TILES = 2


@dataclass(frozen=True)
class RestoreSettings:
    """Tunable knobs for :func:`restore_colour`.

    ``low_clip_pct`` / ``high_clip_pct``: percent of pixels clipped at each end of every channel
    before stretching. ``max_gain``: cap on the per-channel contrast gain. ``saturation_gain``:
    chroma multiplier applied to desaturated images (1.0 disables it). ``clahe``: add mild local
    contrast on lightness.
    """

    low_clip_pct: float = 0.5
    high_clip_pct: float = 0.5
    max_gain: float = 3.0
    saturation_gain: float = 1.15
    clahe: bool = False

    def __post_init__(self) -> None:
        for name in ("low_clip_pct", "high_clip_pct"):
            value = getattr(self, name)
            if not 0.0 <= value < MAX_CLIP_PCT:
                raise ValueError(f"{name} must be in [0, {MAX_CLIP_PCT}), got {value}")
        if self.max_gain < 1.0:
            raise ValueError(f"max_gain must be >= 1, got {self.max_gain}")
        if self.saturation_gain <= 0.0:
            raise ValueError(f"saturation_gain must be > 0, got {self.saturation_gain}")


DEFAULT = RestoreSettings()


def restore_colour(img: np.ndarray, dpi: float, settings: RestoreSettings = DEFAULT) -> np.ndarray:
    """Return a colour-restored copy of an RGB ``uint8`` image scanned at ``dpi``.

    Compatible with the pipeline's ``Enhancer`` signature ``(img, dpi) -> img``.
    """
    _require_rgb_uint8(img)
    if dpi <= 0:
        raise ValueError(f"dpi must be positive, got {dpi}")
    out = _stretch_channels(img, dpi, settings)
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
    if (
        img.dtype != np.uint8
        or img.ndim != RGB_NDIM
        or img.shape[-1] != RGB_CHANNELS
        or not img.size
    ):
        raise ValueError(
            "expected a non-empty uint8 RGB image of shape (H, W, 3), "
            f"got dtype={img.dtype} shape={img.shape}"
        )


def _mm_to_px(mm: float, dpi: float) -> int:
    return round(mm * dpi / MM_PER_INCH)


def _analysis_copy(img: np.ndarray, dpi: float) -> np.ndarray:
    scale = min(1.0, ANALYSIS_DPI / dpi)
    if scale >= 1.0:
        return img
    height, width = img.shape[:2]
    size = (max(1, round(width * scale)), max(1, round(height * scale)))
    return cv2.resize(img, size, interpolation=cv2.INTER_AREA)


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


def _stretch_channels(img: np.ndarray, dpi: float, settings: RestoreSettings) -> np.ndarray:
    pixels = _analysis_copy(img, dpi).reshape(-1, RGB_CHANNELS)
    lows = np.percentile(pixels, settings.low_clip_pct, axis=0)
    highs = np.percentile(pixels, 100.0 - settings.high_clip_pct, axis=0)
    _LOG.debug("restore: channel bounds low=%s high=%s", lows.round(1), highs.round(1))
    luts = [_channel_lut(lo, hi, settings.max_gain) for lo, hi in zip(lows, highs, strict=True)]
    return cv2.LUT(img, np.stack(luts, axis=-1).reshape(LUT_SIZE, 1, RGB_CHANNELS))


def _recover_saturation(img: np.ndarray, gain: float) -> np.ndarray:
    """Scale LAB chroma by ``gain`` if the image is desaturated; neutrals stay exactly neutral."""
    if gain == 1.0:
        return img
    lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)
    chroma = lab[..., 1:].astype(np.float32) - LAB_NEUTRAL
    if float(np.hypot(chroma[..., 0], chroma[..., 1]).mean()) >= DESATURATED_MEAN_CHROMA:
        return img
    boosted = lab.copy()
    boosted[..., 1:] = np.clip(np.rint(chroma * gain + LAB_NEUTRAL), 0, FULL_SCALE).astype(np.uint8)
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
