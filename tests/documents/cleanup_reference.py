"""The paper-cleanup contract transcribed as plainly as possible: the whole page at once, int64,
scalar table formulas, cell loops. Production (banded, vectorised) must equal this exactly.

Only the constants come from production; the checks that pin them are in test_cleanup_tables.
"""

from functools import cache

import cv2
import numpy as np

from fastfoto_linux.documents import auto_colour
from fastfoto_linux.documents.cleanup_tables import (
    BG_SMOOTH_MM,
    BG_WINDOW_MM,
    CELL_MM,
    INK_HI_PCT,
    INK_LO_PCT,
    PAPER_MIN_LEVEL,
    PAPER_PCT,
    PRESETS,
    STOCK_CHROMA,
    TONAL_PCT,
    TONAL_SHARE_PCT,
    Q,
)
from fastfoto_linux.documents.marks import WORK_DPI
from fastfoto_linux.documents.modes import CleanupPolicy, ColourMode
from fastfoto_linux.documents.units import mm_to_px


def odd(size: int) -> int:
    return max(3, size | 1)


def box_mean(values: np.ndarray, size: int) -> np.ndarray:
    total = cv2.boxFilter(
        values.astype(np.float64),
        -1,
        (size, size),
        normalize=False,
        borderType=cv2.BORDER_REPLICATE,
    )
    count = size * size
    return (np.rint(total).astype(np.int64) + count // 2) // count


def _gain(b: int, p: int, preset) -> int:
    full = (p * preset.full_pct + 50) // 100
    none = (p * preset.none_pct + 50) // 100
    if b <= none:
        return Q
    g = min(preset.max_gain_q, max(Q, (preset.target * Q + b // 2) // b))
    r = 256 if b >= full else ((b - none) * 256 + (full - none) // 2) // (full - none)
    return Q + (((g - Q) * r + 128) >> 8)


def _weight(b: int, lum: int) -> int:
    if lum * 100 >= b * INK_HI_PCT:
        return 256
    if lum * 100 <= b * INK_LO_PCT:
        return 0
    num = lum * 100 - b * INK_LO_PCT
    den = b * (INK_HI_PCT - INK_LO_PCT)
    return (num * 256 + den // 2) // den


@cache
def tone_table(policy: CleanupPolicy, p: int) -> np.ndarray:
    preset = PRESETS[policy]
    table = np.empty((256, 256), np.int64)
    for b in range(256):
        gain = _gain(b, p, preset)
        for lum in range(256):
            table[b, lum] = Q + (((gain - Q) * _weight(b, lum) + 128) >> 8)
    return table


def _lowres(grey: np.ndarray, dpi: int):
    height, width = grey.shape
    f = max(1, min(dpi // WORK_DPI, height, width))
    sh, sw = height // f, width // f
    small = grey[: sh * f, : sw * f].reshape(sh, f, sw, f).max(axis=(1, 3))
    size = odd(mm_to_px(BG_WINDOW_MM, dpi / f))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (size, size))
    closed = cv2.morphologyEx(small, cv2.MORPH_CLOSE, kernel)
    smooth = box_mean(closed, odd(mm_to_px(BG_SMOOTH_MM, dpi / f))).astype(np.uint8)
    return f, smooth


def _expand(low: np.ndarray, f: int, height: int, width: int) -> np.ndarray:
    rows = np.minimum(np.arange(height) // f, low.shape[0] - 1)
    cols = np.minimum(np.arange(width) // f, low.shape[1] - 1)
    return low[rows][:, cols].astype(np.int64)


def _protection(lum, b, f, dpi, smooth_shape):
    height, width = lum.shape
    cs = mm_to_px(CELL_MM, dpi / f)
    cell = cs * f
    ch, cw = max(1, height // cell), max(1, width // cell)
    tonal = (lum * 100 > b * INK_LO_PCT) & (lum * 100 < b * TONAL_PCT)
    protected = np.zeros((ch, cw), np.uint8)
    for j in range(ch):
        for i in range(cw):
            y1 = height if j == ch - 1 else (j + 1) * cell
            x1 = width if i == cw - 1 else (i + 1) * cell
            block = tonal[j * cell : y1, i * cell : x1]
            if int(block.sum()) * 100 >= TONAL_SHARE_PCT * block.size:
                protected[j, i] = 1
    protected = cv2.dilate(protected, np.ones((3, 3), np.uint8))
    sh, sw = smooth_shape
    rows = np.minimum(np.arange(sh) // cs, ch - 1)
    cols = np.minimum(np.arange(sw) // cs, cw - 1)
    low = np.where(protected[rows][:, cols] > 0, 0, 256)
    return box_mean(low, odd(cs))


def reference(  # noqa: PLR0911
    src: np.ndarray, dpi: int, output: ColourMode, policy: CleanupPolicy
) -> tuple[str, np.ndarray | None]:
    """(status, pixels or None for the plain render)."""
    if policy is CleanupPolicy.OFF:
        return "off", None
    if output is ColourMode.BW:
        return "bw", None
    colour = src.ndim == 3
    grey = cv2.cvtColor(src, cv2.COLOR_RGB2GRAY) if colour else src
    f, smooth = _lowres(grey, dpi)
    height, width = grey.shape
    histogram = np.cumsum(np.bincount(smooth.ravel(), minlength=256))
    need = (smooth.size * PAPER_PCT + 99) // 100
    paper = int(np.searchsorted(histogram, need))
    if paper < PAPER_MIN_LEVEL:
        return "dark", None
    lum = grey.astype(np.int64)
    b = _expand(smooth, f, height, width)
    if colour:
        wide = src.astype(np.int64)
        c = wide.max(axis=2) - wide.min(axis=2)
        pixels = c[lum * 100 >= b * INK_HI_PCT]
        if pixels.size == 0:
            return "no_paper", None
        running = np.cumsum(np.bincount(pixels, minlength=256))
        pc = int(np.searchsorted(running, (pixels.size + 1) // 2))
        if pc > STOCK_CHROMA and output is ColourMode.COLOUR:
            return "stock", None
    pw = _expand(_protection(lum, b, f, dpi, smooth.shape), f, height, width)
    g = Q + (((tone_table(policy, paper)[b, lum] - Q) * pw + 128) >> 8)
    if colour:
        lo, hi = pc + auto_colour.CHROMA_NOISE, pc + auto_colour.STRONG_CHROMA
        weights = np.array(
            [
                256 if v <= lo else 0 if v >= hi else ((hi - v) * 256 + (hi - lo) // 2) // (hi - lo)
                for v in range(256)
            ],
            np.int64,
        )
        g = Q + (((g - Q) * weights[c] + 128) >> 8)
    if output is ColourMode.GREY:
        return "applied", np.minimum(255, (lum * g + Q // 2) >> 12).astype(np.uint8)
    cap = (255 * Q) // np.maximum(wide.max(axis=2), 1)
    g = np.minimum(g, cap)
    return "applied", np.minimum(255, (wide * g[..., None] + Q // 2) >> 12).astype(np.uint8)
