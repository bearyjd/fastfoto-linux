"""Normative numpy reference for the straighten warp: the definition production must equal."""

import numpy as np

from fastfoto_linux.photo_edits.straighten import sample_coords, straightened_size

SUBPIXEL_BITS = 5
SUBPIXEL_MASK = 31
WEIGHT_ONE = 32


def interpolate(pixels: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Fixed-point bilinear sample at 1/32 px with exact integer weights."""
    height, width = pixels.shape[:2]
    fx, fy = x & SUBPIXEL_MASK, y & SUBPIXEL_MASK
    xi, yi = x >> SUBPIXEL_BITS, y >> SUBPIXEL_BITS
    xj, yj = np.minimum(xi + 1, width - 1), np.minimum(yi + 1, height - 1)
    fx, fy = fx[..., None], fy[..., None]
    p00 = pixels[yi, xi].astype(np.int64)
    p10 = pixels[yi, xj].astype(np.int64)
    p01 = pixels[yj, xi].astype(np.int64)
    p11 = pixels[yj, xj].astype(np.int64)
    mixed = (
        p00 * (WEIGHT_ONE - fx) * (WEIGHT_ONE - fy)
        + p10 * fx * (WEIGHT_ONE - fy)
        + p01 * (WEIGHT_ONE - fx) * fy
        + p11 * fx * fy
    )
    return ((32 * mixed + (1 << 14)) >> 15).astype(np.uint8)


def straightened_frame(pixels: np.ndarray, tenths: int) -> np.ndarray:
    """The whole straightened frame F, computed in one untiled pass."""
    height, width = pixels.shape[:2]
    frame_w, frame_h = straightened_size(width, height, tenths)
    rows, cols = np.mgrid[0:frame_h, 0:frame_w].astype(np.int64)
    x, y = sample_coords(width, height, frame_w, frame_h, tenths, cols, rows)
    return interpolate(pixels, x, y)


def reference_geometry(pixels: np.ndarray, tenths: int, quarter_turns: int, crop) -> np.ndarray:
    """Straighten, crop in F, then turn clockwise, exactly as the contract orders it."""
    frame = straightened_frame(pixels, tenths)
    left, top, right, bottom = crop or (0, 0, frame.shape[1], frame.shape[0])
    turned = np.rot90(frame[top:bottom, left:right], k=-quarter_turns)
    return np.array(turned, dtype=np.uint8, order="C", copy=True)
