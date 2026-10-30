"""Independent scalar white-balance reference, written from the design text alone."""

import math

import numpy as np

REC709 = (0.2126, 0.7152, 0.0722)
GOLDEN_PAIRS = ((100, 0), (-100, 0), (0, 100), (0, -100), (37, -58))


def decode(x: float) -> float:
    return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4


def encode(y: float) -> float:
    return 12.92 * y if y <= 0.0031308 else 1.055 * y ** (1 / 2.4) - 0.055


def raw_gains(temperature: int, tint: int) -> tuple[float, float, float]:
    return 2 ** (temperature / 200), 2 ** (-tint / 200), 2 ** (-temperature / 200)


def luminance(g: tuple[float, float, float]) -> float:
    return REC709[0] * g[0] + REC709[1] * g[1] + REC709[2] * g[2]


def gains(temperature: int, tint: int) -> tuple[float, float, float]:
    g = raw_gains(temperature, tint)
    k = luminance(g)
    return g[0] / k, g[1] / k, g[2] / k


def lut_entry(gain: float, i: int) -> int:
    return math.floor(255 * encode(min(1, gain * decode(i / 255))) + 0.5)


def reference_lut(temperature: int, tint: int) -> np.ndarray:
    """Shape (3, 256) uint8, one row per channel."""
    return np.array(
        [[lut_entry(gain, i) for i in range(256)] for gain in gains(temperature, tint)],
        dtype=np.uint8,
    )


def reference_wb(pixels: np.ndarray, temperature: int, tint: int) -> np.ndarray:
    """Per-pixel scalar oracle: no LUT, no vectorisation."""
    g = gains(temperature, tint)
    result = np.empty_like(pixels)
    for coordinate in np.ndindex(pixels.shape[:2]):
        for channel in range(3):
            result[(*coordinate, channel)] = lut_entry(
                g[channel], int(pixels[(*coordinate, channel)])
            )
    return result
