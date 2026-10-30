"""Linear-light white balance as one 256-entry LUT per channel (see photo-white-balance.md)."""

import math
from threading import Event

import numpy as np

from fastfoto_linux.photo_edits.model import PhotoEditError, PhotoWhiteBalance, check_cancel

# Separate from render.TONE_TILE_PIXELS so tests can shrink each stage's tiles independently.
WB_TILE_PIXELS = 262_144
GAIN_SCALE = 200
REC709 = (0.2126, 0.7152, 0.0722)
RGB_MAX = 255
SRGB_KNEE_ENCODED = 0.04045
SRGB_KNEE_LINEAR = 0.0031308
SRGB_LINEAR_SLOPE = 12.92
SRGB_OFFSET = 0.055
SRGB_GAMMA = 2.4
LEVELS = 256


def _decode(x: float) -> float:
    if x <= SRGB_KNEE_ENCODED:
        return x / SRGB_LINEAR_SLOPE
    return ((x + SRGB_OFFSET) / (1 + SRGB_OFFSET)) ** SRGB_GAMMA


def _encode(y: float) -> float:
    if y <= SRGB_KNEE_LINEAR:
        return SRGB_LINEAR_SLOPE * y
    return (1 + SRGB_OFFSET) * y ** (1 / SRGB_GAMMA) - SRGB_OFFSET


def wb_gains(wb: PhotoWhiteBalance) -> tuple[float, float, float]:
    """Per-channel linear gains whose Rec.709 luminance weighting is exactly 1."""
    raw = (
        2 ** (wb.temperature / GAIN_SCALE),
        2 ** (-wb.tint / GAIN_SCALE),
        2 ** (-wb.temperature / GAIN_SCALE),
    )
    luminance = REC709[0] * raw[0] + REC709[1] * raw[1] + REC709[2] * raw[2]
    return raw[0] / luminance, raw[1] / luminance, raw[2] / luminance


def channel_lut(gain: float) -> np.ndarray:
    """The 256 encoded outputs for one channel's linear gain, rounded half up."""
    return np.array(
        [
            math.floor(RGB_MAX * _encode(min(1, gain * _decode(i / RGB_MAX))) + 0.5)
            for i in range(LEVELS)
        ],
        dtype=np.uint8,
    )


def apply_white_balance(pixels: np.ndarray, wb: PhotoWhiteBalance, cancel: Event) -> None:
    """Balance an owned RGB buffer in place; a neutral balance returns without a pass."""
    if wb == PhotoWhiteBalance():
        return
    luts = [channel_lut(gain) for gain in wb_gains(wb)]
    if not pixels.flags.c_contiguous:
        raise PhotoEditError("white balance needs a contiguous RGB buffer")
    flat = pixels.reshape(-1, 3)
    for start in range(0, len(flat), WB_TILE_PIXELS):
        check_cancel(cancel)
        tile = flat[start : start + WB_TILE_PIXELS]
        for channel, lut in enumerate(luts):
            tile[:, channel] = lut[tile[:, channel]]
