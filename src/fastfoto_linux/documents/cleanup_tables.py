"""Paper cleanup: the constants and the exact integer tables (see ``cleanup``).

Gains are fixed point with ``Q_BITS`` fractional bits (``Q`` is 1.0) and weights run 0 to 256, so
no float touches a pixel and the same page always gives the same bytes.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache

import numpy as np

from fastfoto_linux.documents import auto_colour
from fastfoto_linux.documents.modes import CleanupPolicy

Q_BITS = 12
Q = 1 << Q_BITS
BAND_ROWS = 512  # full-resolution passes work this many rows at a time
# A page whose work grid (the page at WORK_DPI, or at its own dpi when that is lower) has more
# pixels than this is left alone: the integer box sums cost about 42 bytes per work pixel at the
# peak (measured 486 MiB at 12 million), so this bounds the peak near half a gibibyte.
MAX_WORK_PIXELS = 12_000_000

BG_WINDOW_MM = 10.0  # wider than any text stroke: the background estimate never holds ink
BG_SMOOTH_MM = 5.0
CELL_MM = 4.0  # the cells that are checked for a photograph
PAPER_PCT = 90  # the paper level is this percentile of the background
PAPER_MIN_LEVEL = 160  # a page whose paper is darker than this is left alone
STOCK_CHROMA = 16  # coloured paper (colour output only) is left alone above this chroma

INK_LO_PCT = 78  # at or below this share of the local paper a pixel is ink: never changed
INK_HI_PCT = 90  # at or above this share a pixel is paper: changed in full
TONAL_PCT = 92  # between INK_LO_PCT and this share a pixel looks like part of a photograph
TONAL_SHARE_PCT = 20  # a cell with this share of such pixels is protected

_LEVELS = np.arange(256, dtype=np.int64)


@dataclass(frozen=True)
class CleanupPreset:
    target: int  # the paper is lifted towards this level
    max_gain_q: int  # but never by more than this gain
    full_pct: int  # a background at this share of the paper level gets the whole gain
    none_pct: int  # one at or below this share gets none


PRESETS: Mapping[CleanupPolicy, CleanupPreset] = {
    CleanupPolicy.LIGHT: CleanupPreset(245, 4506, 88, 80),
    CleanupPolicy.STRONG: CleanupPreset(255, 5120, 85, 75),
}


def _gain_row(preset: CleanupPreset, paper: int) -> np.ndarray:
    """The gain (Q is 1.0) for every background level 0 to 255."""
    full = (paper * preset.full_pct + 50) // 100
    none = (paper * preset.none_pct + 50) // 100
    b = _LEVELS
    wanted = (preset.target * Q + b // 2) // np.maximum(b, 1)
    gain = np.minimum(preset.max_gain_q, np.maximum(Q, wanted))
    span = max(full - none, 1)
    ramp = np.where(b >= full, 256, ((b - none) * 256 + (full - none) // 2) // span)
    return np.where(b <= none, Q, Q + (((gain - Q) * ramp + 128) >> 8))


def ink_weights() -> np.ndarray:
    """``W[b][l]``: 256 for paper, 0 for ink, a ramp between, at background ``b``, level ``l``."""
    b, level = _LEVELS[:, None], _LEVELS[None, :]
    num = level * 100 - b * INK_LO_PCT
    den = np.maximum(b * (INK_HI_PCT - INK_LO_PCT), 1)
    ramp = (num * 256 + den // 2) // den
    return np.where(
        level * 100 >= b * INK_HI_PCT, 256, np.where(level * 100 <= b * INK_LO_PCT, 0, ramp)
    )


@cache
def tone_table(policy: CleanupPolicy, paper: int) -> np.ndarray:
    """``GT[b][l]`` (int32, 256 x 256, never below ``Q``): the gain of a pixel of level ``l`` on a
    background ``b`` when the page's paper level is ``paper``. Read only."""
    gain = _gain_row(PRESETS[policy], paper)[:, None]
    table = (Q + (((gain - Q) * ink_weights() + 128) >> 8)).astype(np.int32)
    table.flags.writeable = False
    return table


@cache
def chroma_weights(paper_chroma: int) -> np.ndarray:
    """``WC[c]`` (int32, 256): 256 for a chroma within noise of the paper's, 0 for strong colour."""
    lo = paper_chroma + auto_colour.CHROMA_NOISE
    hi = paper_chroma + auto_colour.STRONG_CHROMA
    c = _LEVELS
    ramp = ((hi - c) * 256 + (hi - lo) // 2) // (hi - lo)
    table = np.where(c <= lo, 256, np.where(c >= hi, 0, ramp)).astype(np.int32)
    table.flags.writeable = False
    return table


def channel_caps() -> np.ndarray:
    """``CAP[m]``: the largest gain that keeps a pixel whose brightest channel is ``m`` in range."""
    return ((255 * Q) // np.maximum(_LEVELS, 1)).astype(np.int32)
