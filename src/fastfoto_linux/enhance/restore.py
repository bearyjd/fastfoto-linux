"""Colour restoration for faded, colour-cast prints.

Deterministic and classic (no machine learning), in three stages:

1. *Simplest Color Balance* (Limare, Lisani, Morel, Petro, Sbert, IPOL 2011): clip a small
   percentile of every channel at both ends and stretch what is left to the full scale. This
   removes the cast and restores contrast. Percentiles are exact, from full-resolution 256-bin
   histograms, so the clipped fraction is what the settings say at any resolution. The stretch
   is applied as two moves: first every channel is balanced onto a common range (this removes
   the cast and is never limited), then one common brightness/contrast move is applied to all
   channels (this is the part that is capped and held back for low-key images).
2. Gentle saturation recovery on LAB chroma, scaled by how desaturated the image measurably is.
3. Optional mild local contrast (CLAHE on lightness), off by default.

Safeguards keep unusual images from being damaged:

* Run this on the cropped photo. Pixels that are nearly black or nearly white in all three
  channels (a scanner border or background; JPEG scans never hold exact 0 / 255) are ignored
  when measuring, so a frame cannot pin the percentiles, and they are left untouched.
* A channel that already spans nearly the full scale, or is flat, is left alone.
* A monochrome print (black and white, sepia, any single-hue tone) is stretched with ONE shared
  curve so its tone is kept. It is recognised by an almost zero hue scatter around its mean
  colour. A colour cast shifts the mean but leaves the scene's scatter, so a cast print is never
  taken for a tone: when in doubt, the cast is removed.
* The common move never pushes the median below a fixed fraction of the scale or brightens a
  low-key image by more than a small gain, so night scenes are not crushed or washed out.

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

FRAME_BLACK_MAX = 2  # pixels with every channel <= this ...
FRAME_WHITE_MIN = 253  # ... or every channel >= this are scanner border/background
MAX_CLIP_PCT = 50.0  # each tail must stay below the median
MAX_SATURATION_GAIN = 3.0
SKIP_RANGE_FRACTION = 0.95  # a channel spanning this much of the scale needs no stretch
MIN_RANGE_LEVELS = 8  # a channel narrower than this is flat: stretching it would be noise
MIN_OUTPUT_MEDIAN_FRACTION = 0.2  # the common move may not push the median below this of the scale
LOW_KEY_FULL_GAIN_MEDIAN = 96.0  # at and above this median the full gain cap applies; below, less
STAT_MAX_PIXELS = 250_000  # colour statistics use a block-averaged copy of about this size
NEUTRAL_MEAN_CHROMA = 3.0  # mean LAB chroma below this: a black-and-white print
NO_DIRECTION_LENGTH = 1e-6  # a mean colour this short has no direction
TONE_MAX_HUE_SCATTER = 0.8  # std of a*, b* across the mean colour's direction: below = one tone
SHARED_MIN_SPAN_FRACTION = 0.6  # shared stretch only if tonal range, not channel offsets, dominates
DESATURATED_MEAN_CHROMA = 10.0  # saturation recovery fades out as mean chroma reaches this
CLAHE_CLIP_LIMIT = 1.5  # subtle: close to plain histogram equalisation's lower bound
CLAHE_TILE_MM = 25.0
CLAHE_MIN_TILES = 2


@dataclass(frozen=True)
class RestoreSettings:
    """Tunable knobs for :func:`restore_colour`.

    ``low_clip_pct`` / ``high_clip_pct``: percent of pixels clipped at each end of every channel
    before stretching. ``max_gain``: cap on the contrast gain of the common move and on the
    relative gain between channels. ``saturation_gain``:
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


def _frame_mask(img: np.ndarray) -> np.ndarray:
    """255 where a pixel is (nearly) black or white in all channels: scanner border/background."""
    black = cv2.inRange(img, (0,) * RGB_CHANNELS, (FRAME_BLACK_MAX,) * RGB_CHANNELS)
    white = cv2.inRange(img, (FRAME_WHITE_MIN,) * RGB_CHANNELS, (FULL_SCALE,) * RGB_CHANNELS)
    return black | white


def _histograms(img: np.ndarray, frame: np.ndarray) -> np.ndarray:
    """Exact per-channel 256-bin histograms of the pixels outside the frame."""
    hists = np.stack(
        [np.bincount(img[..., c].ravel(), minlength=LUT_SIZE) for c in range(RGB_CHANNELS)]
    )
    inside = frame.astype(bool)
    if inside.any():
        hists -= np.stack(
            [np.bincount(img[..., c][inside], minlength=LUT_SIZE) for c in range(RGB_CHANNELS)]
        )
    return hists


def _channel_stats(
    hist: np.ndarray, settings: RestoreSettings
) -> tuple[float, float, float] | None:
    """Black point, white point and median of one channel, or ``None`` without pixels.

    At most ``low_clip_pct`` / ``high_clip_pct`` of the pixels lie at or beyond the black/white
    point, so clipping can never exceed what the settings say.
    """
    total = int(hist.sum())
    if total == 0:
        return None
    cdf = np.cumsum(hist)
    low = max(int(np.searchsorted(cdf, total * settings.low_clip_pct / 100.0, "right")) - 1, 0)
    reach = total * (1.0 - settings.high_clip_pct / 100.0)
    high = min(int(np.searchsorted(cdf, reach, "left")) + 1, FULL_SCALE)
    median = int(np.searchsorted(cdf, total / 2.0, "left"))
    return float(low), float(high), float(median)


def _affine_lut(gain: float, offset: float) -> np.ndarray:
    levels = np.arange(LUT_SIZE, dtype=np.float32)
    return np.clip(np.rint(gain * levels + offset), 0, FULL_SCALE).astype(np.uint8)


def _common_move(low: float, high: float, median: float, max_gain: float) -> tuple[float, float]:
    """(gain, offset) of the brightness/contrast move shared by all channels.

    Stretches ``[low, high]`` to the full scale, except that the black point is held back so
    the median stays above ``MIN_OUTPUT_MEDIAN_FRACTION`` of the scale, and the gain is capped
    (less for low-key images) by blending with the identity.
    """
    ceiling = (median - MIN_OUTPUT_MEDIAN_FRACTION * high) / (1.0 - MIN_OUTPUT_MEDIAN_FRACTION)
    black = min(low, max(ceiling, 0.0))
    span = high - black
    if span >= SKIP_RANGE_FRACTION * FULL_SCALE:
        return 1.0, 0.0
    full_gain = FULL_SCALE / span
    cap = 1.0 + (max_gain - 1.0) * min(1.0, median / LOW_KEY_FULL_GAIN_MEDIAN)
    if full_gain <= cap:
        return full_gain, -black * full_gain
    weight = (cap - 1.0) / (full_gain - 1.0)
    return cap, -weight * full_gain * black


def _sample_ab(img: np.ndarray, frame: np.ndarray) -> np.ndarray:
    """LAB a*, b* offsets (N, 2) of a block-averaged copy, blocks touching the frame excluded.

    Averaging blocks of pixels removes scan noise from the colour statistics.
    """
    height, width = img.shape[:2]
    scale = min(1.0, math.sqrt(STAT_MAX_PIXELS / (height * width)))
    if scale < 1.0:
        size = (max(1, round(width * scale)), max(1, round(height * scale)))
        img = cv2.resize(img, size, interpolation=cv2.INTER_AREA)
        frame = cv2.resize(frame, size, interpolation=cv2.INTER_AREA)
    lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)
    return lab[frame == 0][:, 1:].astype(np.float32) - LAB_NEUTRAL


def _mean_chroma(ab: np.ndarray) -> float:
    return float(np.hypot(ab[:, 0], ab[:, 1]).mean()) if len(ab) else 0.0


def _hue_scatter(ab: np.ndarray) -> float:
    """Std of a*, b* across the direction of the mean colour (all directions if it is neutral).

    Variation along the mean colour's direction is only chroma changing with lightness, as in
    sepia; variation across it is a different colour.
    """
    mean = ab.mean(axis=0)
    deviation = ab - mean
    length = float(np.hypot(*mean))
    if length < NO_DIRECTION_LENGTH:
        return float(np.sqrt((deviation**2).sum(axis=1).mean()))
    across = deviation @ np.array([-mean[1], mean[0]]) / length
    return float(across.std())


def _is_single_tone(ab: np.ndarray) -> bool:
    """True for black and white, sepia and other prints whose colour is a single tone."""
    if not len(ab):
        return False
    return _mean_chroma(ab) < NEUTRAL_MEAN_CHROMA or _hue_scatter(ab) < TONE_MAX_HUE_SCATTER


def _shared_luts(
    stats: list[tuple[float, float, float]], max_gain: float
) -> list[np.ndarray] | None:
    """One curve for all channels (keeps the tone), or ``None`` if channel offsets dominate.

    A flat coloured image has tiny tonal range in every channel but large differences between
    channels; a shared stretch would read those differences as range and wreck the colour.
    """
    low = min(lo for lo, _, _ in stats)
    high = max(hi for _, hi, _ in stats)
    widest = max(hi - lo for lo, hi, _ in stats)
    if high - low < MIN_RANGE_LEVELS or widest < SHARED_MIN_SPAN_FRACTION * (high - low):
        return None
    median = sum(m for _, _, m in stats) / len(stats)
    return [_affine_lut(*_common_move(low, high, median, max_gain))] * RGB_CHANNELS


def _balanced_luts(stats: list[tuple[float, float, float]], max_gain: float) -> list[np.ndarray]:
    """Per-channel curves: balance every channel onto a common range, then one common move."""
    luts = [_affine_lut(1.0, 0.0)] * RGB_CHANNELS
    active = [
        i
        for i, (lo, hi, _) in enumerate(stats)
        if MIN_RANGE_LEVELS <= hi - lo < SKIP_RANGE_FRACTION * FULL_SCALE
    ]
    if not active:
        return luts
    ref_low = sum(stats[i][0] for i in active) / len(active)
    ref_high = sum(stats[i][1] for i in active) / len(active)
    ref_median = sum(stats[i][2] for i in active) / len(active)
    gain, offset = _common_move(ref_low, ref_high, ref_median, max_gain)
    ref_mid = (ref_low + ref_high) / 2.0
    for i in active:
        low, high, _ = stats[i]
        balance = min(max((ref_high - ref_low) / (high - low), 1.0 / max_gain), max_gain)
        shift = ref_mid - (low + high) / 2.0 * balance
        luts[i] = _affine_lut(gain * balance, gain * shift + offset)
    return luts


def _stretch_channels(img: np.ndarray, settings: RestoreSettings) -> np.ndarray:
    frame = _frame_mask(img)
    stats = [_channel_stats(h, settings) for h in _histograms(img, frame)]
    if any(st is None for st in stats):  # nothing but frame: nothing to measure
        return img.copy()
    _LOG.debug("restore: channel black/white/median %s", stats)
    luts = None
    if _is_single_tone(_sample_ab(img, frame)):
        luts = _shared_luts(stats, settings.max_gain)
    if luts is None:
        luts = _balanced_luts(stats, settings.max_gain)
    out = cv2.LUT(img, np.stack(luts, axis=-1).reshape(LUT_SIZE, 1, RGB_CHANNELS))
    inside = frame.astype(bool)
    out[inside] = img[inside]  # the frame is never touched
    return out


def _recover_saturation(img: np.ndarray, gain: float) -> np.ndarray:
    """Scale LAB chroma up in proportion to the measured desaturation; neutrals stay neutral."""
    if gain == 1.0:
        return img
    deficit = 1.0 - _mean_chroma(_sample_ab(img, _frame_mask(img))) / DESATURATED_MEAN_CHROMA
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
