"""Fixed-point straighten maths: trig table, inscribed frame, sample coordinates and warp.

A leaf module: it imports only math, numpy and cv2, never the model. The integer reference in
the tests (tests/photo_edits/straighten_reference.py) is the normative definition of the warp;
cv2.remap is used only because it reproduces that reference bit for bit.
"""

import math

import cv2
import numpy as np

STRAIGHTEN_LIMIT_TENTHS = 150
TRIG_BITS = 24
SUBPIXEL = 32
TILE = 512
SUBPIXEL_BITS = 5
SUBPIXEL_MASK = SUBPIXEL - 1
ROI_LIMIT = 32767


def trig(tenths: int) -> tuple[int, int]:
    """Signed fixed-point (cos, sin) of tenths of a degree, scaled by 2**24."""
    angle = math.radians(tenths / 10)
    return round(math.cos(angle) * (1 << TRIG_BITS)), round(math.sin(angle) * (1 << TRIG_BITS))


def sample_coords(  # noqa: PLR0913, PLR0917 - the full frame and source geometry are the contract
    width: int, height: int, frame_w: int, frame_h: int, tenths: int, cols, rows
):
    """Source pixel-index coordinates in 1/32 px for straightened-frame indices (int64)."""
    cos, sin = trig(tenths)
    u2 = 2 * cols - (frame_w - 1)
    v2 = 2 * rows - (frame_h - 1)
    half = 1 << (TRIG_BITS - 1)
    x = ((((width - 1) << TRIG_BITS) + u2 * cos + v2 * sin) * 16 + half) >> TRIG_BITS
    y = ((((height - 1) << TRIG_BITS) - u2 * sin + v2 * cos) * 16 + half) >> TRIG_BITS
    return x, y


def _fits(width: int, height: int, tenths: int, frame_w: int, frame_h: int) -> tuple[bool, bool]:
    """Whether the four frame corners sample inside the source along x and along y."""
    cols = (0, frame_w - 1, 0, frame_w - 1)
    rows = (0, 0, frame_h - 1, frame_h - 1)
    xs, ys = zip(
        *(
            sample_coords(width, height, frame_w, frame_h, tenths, c, r)
            for c, r in zip(cols, rows, strict=True)
        ),
        strict=True,
    )
    inside_x = all(0 <= x <= SUBPIXEL * (width - 1) for x in xs)
    inside_y = all(0 <= y <= SUBPIXEL * (height - 1) for y in ys)
    return inside_x, inside_y


def _estimate(width: int, height: int, tenths: int) -> tuple[float, float]:
    """Float max-area axis-aligned rectangle inscribed in the rotated pixel-centre grid."""
    angle = math.radians(abs(tenths) / 10)
    s, c = math.sin(angle), math.cos(angle)
    w, h = width - 1, height - 1
    if w == 0 or h == 0:
        return 0.0, 0.0
    if min(w, h) <= 2 * s * c * max(w, h):
        half = min(w, h) / 2
        return (half / s, half / c) if w >= h else (half / c, half / s)
    denominator = c * c - s * s
    return (w * c - h * s) / denominator, (h * c - w * s) / denominator


def straightened_size(width: int, height: int, tenths: int) -> tuple[int, int]:
    """The largest axis-aligned frame whose every sample lies inside the source."""
    if tenths == 0:
        return width, height
    est_w, est_h = _estimate(width, height, tenths)
    frame_w = max(1, min(width, math.floor(est_w) + 1))
    frame_h = max(1, min(height, math.floor(est_h) + 1))
    while True:
        inside_x, inside_y = _fits(width, height, tenths, frame_w, frame_h)
        if inside_x and inside_y:
            break
        shrink_w = not inside_x and frame_w > 1
        shrink_h = not inside_y and frame_h > 1
        if not shrink_w and not shrink_h:  # the other axis must give way
            shrink_w, shrink_h = frame_w > 1, frame_w == 1
        frame_w -= shrink_w
        frame_h -= shrink_h
    while frame_w < width and all(_fits(width, height, tenths, frame_w + 1, frame_h)):
        frame_w += 1
    while frame_h < height and all(_fits(width, height, tenths, frame_w, frame_h + 1)):
        frame_h += 1
    return frame_w, frame_h


def warp_tile(pixels: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Bilinear sample at 1/32 px, bit-identical to the normative integer reference."""
    height, width = pixels.shape[:2]
    x0, y0 = int(x.min()) >> SUBPIXEL_BITS, int(y.min()) >> SUBPIXEL_BITS
    x1 = min(width, (int(x.max()) >> SUBPIXEL_BITS) + 2)
    y1 = min(height, (int(y.max()) >> SUBPIXEL_BITS) + 2)
    if x1 - x0 >= ROI_LIMIT or y1 - y0 >= ROI_LIMIT:
        raise ValueError("Straighten tile is too large for the fixed-point remap.")
    roi = np.ascontiguousarray(pixels[y0:y1, x0:x1])
    map1 = np.stack(((x >> SUBPIXEL_BITS) - x0, (y >> SUBPIXEL_BITS) - y0), axis=-1)
    map2 = ((y & SUBPIXEL_MASK) << SUBPIXEL_BITS) | (x & SUBPIXEL_MASK)
    return cv2.remap(
        roi,
        map1.astype(np.int16),
        map2.astype(np.uint16),
        cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE,
    )
