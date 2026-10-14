"""Colour restoration for faded, colour-cast prints.

Deterministic and classic (no machine learning), in three stages:

1. *Simplest Color Balance* (Limare, Lisani, Morel, Petro, Sbert, IPOL 2011): clip a small
   percentile of every channel at both ends and stretch what is left to the full scale. Percentiles
   are exact, from full-resolution 256-bin histograms, so the clipped fraction is what the
   settings say at any resolution. The stretch is two moves. One common brightness/contrast move
   restores contrast (capped, and held back for low-key images). Only when the print shows
   evidence of a cast are the channels also balanced onto a common range first (black points
   aligned, gains matched), which removes the cast.
2. Gentle saturation recovery on LAB chroma, scaled by how desaturated the image measurably is.
3. Optional mild local contrast (CLAHE on lightness), off by default.

Cast evidence (``restore_cast.cast_evidence``): the pixels that a provisional full balance turns
neutral are the ones a cast would have tinted, and their mean colour offset in the print is the
evidence. A scene that is mostly one hue (sand, an amber sunset, skin, a lawn) has no such
pixels, or they are already neutral, so its channels are never balanced: it keeps its hue and
chroma. Without evidence the common move is applied to the luminance only, like a tone: every
pixel keeps its own colour offsets, so a cast that is not removed is never amplified either.

Safeguards keep unusual images from being damaged:

* Run this on the cropped photo. Rows and columns along the image edge that are (nearly) all
  white or black (a scanner border or background, any JPEG-noisy 248-255 or 0-6) form a frame:
  it is ignored when measuring and left untouched. Only whole edge lines count, so bright or
  dark pixels inside the photo (highlights, shadows) are measured like any other.
* A channel that already spans nearly the full scale, or is flat, is left alone.
* A monochrome print (black and white, sepia, any single-hue tone) is recognised by an almost
  zero hue scatter around its mean colour (a few percent of coloured ink are ignored) and gets
  the luminance-only stretch: the tone is neither neutralised nor amplified. A colour cast
  shifts the mean but leaves the scene's scatter, so a cast print is taken for a tone only when
  its scene is nearly colourless (scene chroma up to about 3, up to about 6 on a very dark
  print): the cast is then kept, never amplified.
* The common move is skipped for near-white pages (print backs), never pushes the median below
  a fixed fraction of the scale and brightens a low-key image only a little.
* Trade-off: casts are removed by aligning the channels' black points and matching their
  gains. A black point moves no further than the cast measured at the neutrals supports:
  ``BLACK_SHIFT_PER_CHROMA`` levels per unit of evidence, at least ``BLACK_SHIFT_FLOOR`` (so at
  least 15 once the evidence threshold is met). No channel is stretched more than
  ``MAX_CHANNEL_GAIN_RATIO`` times the widest one. A cast that needs a larger channel-gain
  mismatch leaves no neutral pixel after the balance, so it gives no evidence and is left alone;
  so is a cast on a print whose neutrals are not tinted enough (below ``CAST_EVIDENCE_CHROMA``).
  A scene with one dominant colour and no neutral part at all can still be taken for a cast.

Known limitation: a cream or aged margin with any channel below ``FRAME_WHITE_MIN`` is not a
frame, so it is measured and recoloured like the photo.

The input array is never modified.
"""

import logging
import math
from dataclasses import dataclass

import cv2
import numpy as np

from fastfoto_linux.enhance.restore_cast import (
    CAST_EVIDENCE_CHROMA,
    LAB_NEUTRAL,
    ab_offsets,
    block_average,
    cast_evidence,
    is_single_tone,
    mean_chroma,
    sample_ab,
)
from fastfoto_linux.pipeline.geometry import mm_to_px

_LOG = logging.getLogger(__name__)

FULL_SCALE = 255
LUT_SIZE = FULL_SCALE + 1
RGB_NDIM = 3
RGB_CHANNELS = 3

FRAME_BLACK_MAX = 6  # edge lines whose pixels have every channel <= this ...
FRAME_WHITE_MIN = 248  # ... or every channel >= this are scanner border/background
FRAME_LINE_FRACTION = 0.95  # share of a line that must be frame-coloured (dust, noise tolerated)
MAX_CLIP_PCT = 50.0  # each tail must stay below the median
MAX_SATURATION_GAIN = 3.0
SKIP_RANGE_FRACTION = 0.95  # a channel spanning this much of the scale needs no stretch
MIN_RANGE_LEVELS = 8  # a channel narrower than this is flat: stretching it would be noise
MIN_OUTPUT_MEDIAN_FRACTION = 0.2  # the common move may not push the median below this of the scale
NEAR_WHITE_MEDIAN_FRACTION = 0.97  # a median this close to white: a page, not a photo
MAX_CHANNEL_GAIN_RATIO = 1.5  # no channel is stretched more than this times the widest one
LOW_KEY_FULL_GAIN_MEDIAN = 96.0  # at and above this median the full gain cap applies; below, less
BLACK_SHIFT_FLOOR = 12.0  # levels a channel's black point may always move when aligned
BLACK_SHIFT_PER_CHROMA = 1.5  # further levels per unit of cast chroma measured at the neutrals
DESATURATED_MEAN_CHROMA = 10.0  # saturation recovery fades out as mean chroma reaches this
CLAHE_CLIP_LIMIT = 1.5  # subtle: close to plain histogram equalisation's lower bound
CLAHE_TILE_MM = 25.0
CLAHE_MIN_TILES = 2


@dataclass(frozen=True)
class RestoreSettings:
    """Tunable knobs for :func:`restore_colour`.

    ``low_clip_pct`` / ``high_clip_pct``: percent of pixels clipped at each end of every channel
    before stretching. ``max_gain``: cap on the contrast gain of the common move.
    ``saturation_gain``: chroma multiplier reached by a fully desaturated image (1.0 disables
    recovery; images with mean chroma of ``DESATURATED_MEAN_CHROMA`` or more are never boosted).
    ``clahe``: add mild local contrast on lightness.
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
    box = _frame_box(img)
    out = _stretch_channels(img, box, settings)
    out = _recover_saturation(out, settings.saturation_gain, box)
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


def _inner_span(is_frame: np.ndarray) -> tuple[int, int]:
    """Start and stop of the lines left once frame lines are peeled off both ends."""
    content = np.flatnonzero(~is_frame)
    return (int(content[0]), int(content[-1]) + 1) if len(content) else (0, 0)


def _frame_box(img: np.ndarray) -> tuple[int, int, int, int] | None:
    """(top, bottom, left, right) of the photo inside its scanner frame, ``None`` if all frame.

    A frame is made of whole rows/columns along the image edge that are (nearly) all white or
    black, so highlights and shadows inside the photo are never mistaken for it.
    """
    framed = cv2.inRange(img, (FRAME_WHITE_MIN,) * RGB_CHANNELS, (FULL_SCALE,) * RGB_CHANNELS)
    framed |= cv2.inRange(img, (0,) * RGB_CHANNELS, (FRAME_BLACK_MAX,) * RGB_CHANNELS)
    width = framed.shape[1]
    top, bottom = _inner_span(np.count_nonzero(framed, axis=1) >= FRAME_LINE_FRACTION * width)
    if top >= bottom:
        return None
    rows = framed[top:bottom]
    left, right = _inner_span(
        np.count_nonzero(rows, axis=0) >= FRAME_LINE_FRACTION * (bottom - top)
    )
    return None if left >= right else (top, bottom, left, right)


def _histograms(inner: np.ndarray) -> np.ndarray:
    """Exact per-channel 256-bin histograms."""
    return np.stack(
        [np.bincount(inner[..., c].ravel(), minlength=LUT_SIZE) for c in range(RGB_CHANNELS)]
    )


def _channel_stats(hist: np.ndarray, settings: RestoreSettings) -> tuple[float, float, float]:
    """Black point, white point and median of one histogram.

    At most ``low_clip_pct`` / ``high_clip_pct`` of the pixels lie at or beyond the black/white
    point, so clipping can never exceed what the settings say.
    """
    total = int(hist.sum())
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
    if median >= NEAR_WHITE_MEDIAN_FRACTION * FULL_SCALE:  # a page, not a photo: already white
        return 1.0, 0.0
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


def _luminance_move(inner: np.ndarray, gain: float, offset: float) -> np.ndarray:
    """Apply a move to the luminance only: every pixel keeps its own colour offsets."""
    luma = cv2.transform(inner, np.full((1, RGB_CHANNELS), 1.0 / RGB_CHANNELS, np.float32))
    delta = _affine_lut(gain, offset)[luma].astype(np.int16) - luma
    return np.clip(inner.astype(np.int16) + delta[..., None], 0, FULL_SCALE).astype(np.uint8)


def _stretch_luminance(inner: np.ndarray, settings: RestoreSettings) -> np.ndarray:
    """Common move, measured on the luminance, applied to the luminance only."""
    luma = cv2.transform(inner, np.full((1, RGB_CHANNELS), 1.0 / RGB_CHANNELS, np.float32))
    low, high, median = _channel_stats(np.bincount(luma.ravel(), minlength=LUT_SIZE), settings)
    if high - low < MIN_RANGE_LEVELS:
        return inner.copy()
    return _luminance_move(inner, *_common_move(low, high, median, settings.max_gain))


def _balances(spans: list[float], reference: float) -> list[float]:
    """Per-channel gains matching each span to ``reference``, narrow channels capped.

    No channel is stretched more than ``MAX_CHANNEL_GAIN_RATIO`` times the gain of the widest
    one, so a scene that is mostly one hue (lawn, sea) is not neutralised.
    """
    gains = [reference / span for span in spans]
    ceiling = min(gains) * MAX_CHANNEL_GAIN_RATIO
    return [min(gain, ceiling) for gain in gains]


def _active_channels(stats: list[tuple[float, float, float]]) -> list[int]:
    """Channels that need a stretch: not flat, not already spanning (nearly) the full scale."""
    return [
        i
        for i, (lo, hi, _) in enumerate(stats)
        if MIN_RANGE_LEVELS <= hi - lo < SKIP_RANGE_FRACTION * FULL_SCALE
    ]


def _reference(
    stats: list[tuple[float, float, float]], active: list[int]
) -> tuple[float, float, float]:
    """Black point, white point and median averaged over the active channels."""
    low, high, median = (sum(stats[i][k] for i in active) / len(active) for k in range(3))
    return low, high, median


def _balanced_luts(
    stats: list[tuple[float, float, float]], max_gain: float, shift_limit: float
) -> list[np.ndarray]:
    """Per-channel curves: black points aligned, gains balanced, then one common move.

    No channel's black point moves more than ``shift_limit`` levels when it is aligned.
    """
    luts = [_affine_lut(1.0, 0.0)] * RGB_CHANNELS
    active = _active_channels(stats)
    if not active:
        return luts
    ref_low, ref_high, ref_median = _reference(stats, active)
    gain, offset = _common_move(ref_low, ref_high, ref_median, max_gain)
    balances = _balances([stats[i][1] - stats[i][0] for i in active], ref_high - ref_low)
    for i, balance in zip(active, balances, strict=True):
        low = stats[i][0]
        target = low + min(max(ref_low - low, -shift_limit), shift_limit)
        luts[i] = _affine_lut(gain * balance, gain * (target - low * balance) + offset)
    return luts


def _black_shift_limit(evidence: float) -> float:
    raise NotImplementedError


def _cast_evidence(
    sample: np.ndarray, ab: np.ndarray, stats: list[tuple[float, float, float]]
) -> float:
    """Evidence of a colour cast, from the pixels a full provisional balance turns neutral."""
    luts = np.stack(_balanced_luts(stats, 1.0, math.inf), axis=-1)
    balanced = cv2.LUT(sample, luts.reshape(LUT_SIZE, 1, RGB_CHANNELS))
    return cast_evidence(ab, ab_offsets(balanced))


def _restore_inner(inner: np.ndarray, settings: RestoreSettings) -> np.ndarray:
    """Stretch a photo (frame already removed) in the way its colours allow.

    A single tone gets a luminance-only stretch. Otherwise every channel gets the common move,
    and the channels are balanced against each other only if the print shows evidence of a cast.
    """
    sample = block_average(inner)
    ab = ab_offsets(sample)
    if is_single_tone(ab):
        return _stretch_luminance(inner, settings)
    stats = [_channel_stats(h, settings) for h in _histograms(inner)]
    _LOG.debug("restore: channel black/white/median %s", stats)
    evidence = _cast_evidence(sample, ab, stats)
    if evidence < CAST_EVIDENCE_CHROMA:
        active = _active_channels(stats)
        if not active:
            return inner.copy()
        return _luminance_move(inner, *_common_move(*_reference(stats, active), settings.max_gain))
    limit = max(BLACK_SHIFT_FLOOR, BLACK_SHIFT_PER_CHROMA * evidence)
    luts = np.stack(_balanced_luts(stats, settings.max_gain, limit), axis=-1)
    return cv2.LUT(inner, luts.reshape(LUT_SIZE, 1, RGB_CHANNELS))


def _stretch_channels(
    img: np.ndarray, box: tuple[int, int, int, int] | None, settings: RestoreSettings
) -> np.ndarray:
    out = img.copy()
    if box is None:  # nothing but frame: nothing to measure
        return out
    top, bottom, left, right = box
    out[top:bottom, left:right] = _restore_inner(img[top:bottom, left:right], settings)
    return out


def _recover_saturation(
    img: np.ndarray, gain: float, box: tuple[int, int, int, int] | None
) -> np.ndarray:
    """Scale LAB chroma up in proportion to the measured desaturation; neutrals stay neutral."""
    if gain == 1.0 or box is None:
        return img
    top, bottom, left, right = box
    deficit = 1.0 - mean_chroma(sample_ab(img[top:bottom, left:right])) / DESATURATED_MEAN_CHROMA
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
    tile_px = max(1, mm_to_px(CLAHE_TILE_MM, dpi))
    grid = (
        max(CLAHE_MIN_TILES, round(width / tile_px)),
        max(CLAHE_MIN_TILES, round(height / tile_px)),
    )
    clahe = cv2.createCLAHE(clipLimit=CLAHE_CLIP_LIMIT, tileGridSize=grid)
    lab[..., 0] = clahe.apply(lab[..., 0])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)
