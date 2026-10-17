"""A thin light streak down the scanner's backing band is the scanner's, not content.

A fleck on the scanner's glass or backing prints as a faint light vertical line down the band, a
pixel or two wide and 12 to 15 levels brighter than the backing. By colour it is not backing, so
the last check of a band cut (see ``guard``) found something in the strip and cancelled the cut;
and where the line splits the band, the far part may reach neither a side of the strip (a wedge of
pad is there) nor its first row (shadow tone is there), and is no longer backing either.

In the strip of a band cut a pixel can be a streak's when it is not backing, backing lies
``STREAK_MAX_MM`` to its left and to its right (rounded up to whole pixels, and at least
``STREAK_MIN_OFFSET_PX``), and it is ``STREAK_LIGHTER`` levels brighter (mean of the channels) than
the brighter of those two neighbours. A column is a streak's when that holds in ``STREAK_SHARE`` of
the rows that have backing on both sides of it, and those rows are ``STREAK_MIN_MM`` tall in all.
The width follows from the neighbours: a line has backing within 0.3 mm of each of its pixels only
if it is up to about twice that wide, so with its blurred edge a streak may be a little wider than
0.3 mm; a run of streak columns wider than the offset is none (a line that leans across the band
meets one column after the other). The streak and its blurred edge, one pixel each side in the same
rows, count as backing before it is judged whether the backing joins a side, so the line joins the
parts of the band it splits.

Only a lighter line is forgiven: ink darkens, so a dark streak still keeps the strip, and so do a
light line wider than that, one over under ``STREAK_SHARE`` of the rows, and one that leans.
"""

import math

import numpy as np

from fastfoto_linux.documents.band import backing_mask
from fastfoto_linux.documents.units import MM_PER_INCH

STREAK_MAX_MM = 0.3  # backing lies this far to each side of a streak's pixel (whole pixels, up)
STREAK_LIGHTER = 4.0  # levels brighter (mean of RGB) than the brighter of the two neighbours
STREAK_SHARE = 0.9  # of the rows that have backing on both sides of the column
STREAK_MIN_MM = 3.0  # and those rows are at least this tall in all (a band is 3 mm or more)
STREAK_MIN_OFFSET_PX = 2  # one pixel is noise at any resolution
STREAK_TINT = 12.0  # its blue minus red is within this of the backing's


def _offset_px(dpi: int) -> int:
    """``STREAK_MAX_MM`` in whole pixels, rounded up and never under ``STREAK_MIN_OFFSET_PX``."""
    return max(STREAK_MIN_OFFSET_PX, math.ceil(STREAK_MAX_MM * dpi / MM_PER_INCH))


def _beside(values: np.ndarray, offset: int, fill: float) -> tuple[np.ndarray, np.ndarray]:
    """``values`` of the pixel ``offset`` columns to the left and to the right of every pixel
    (``fill`` beyond the strip). New arrays: ``values`` is not changed."""
    left = np.full_like(values, fill)
    right = np.full_like(values, fill)
    left[:, offset:] = values[:, : values.shape[1] - offset]
    right[:, : values.shape[1] - offset] = values[:, offset:]
    return left, right


def _candidates(smooth: np.ndarray, backing: np.ndarray, offset: int) -> tuple[np.ndarray, ...]:
    """The pixels that could be a streak's, and the pixels with backing on both sides."""
    bright = smooth.mean(axis=2)
    left_backing, right_backing = _beside(backing, offset, False)
    left_bright, right_bright = _beside(bright, offset, 0.0)
    beside = left_backing & right_backing
    lighter = bright >= np.maximum(left_bright, right_bright) + STREAK_LIGHTER
    return ~backing & beside & lighter, beside


def _columns(candidates: np.ndarray, beside: np.ndarray, dpi: int) -> np.ndarray:
    """The columns where enough rows with backing on both sides hold a candidate."""
    support = beside.sum(axis=0)
    long_enough = support >= STREAK_MIN_MM * dpi / MM_PER_INCH
    return long_enough & (candidates.sum(axis=0) >= STREAK_SHARE * support)


def _narrow_runs(columns: np.ndarray, limit: int) -> np.ndarray:
    """``columns`` without the runs of more than ``limit`` neighbouring columns: a line that
    leans across the band meets one column after the other, and a light bar is no streak."""
    edges = np.flatnonzero(np.diff(columns.astype(np.int8), prepend=0, append=0))
    narrow = columns.copy()
    for start, end in zip(edges[::2], edges[1::2], strict=True):
        if end - start > limit:
            narrow[start:end] = False
    return narrow


def streak_pixels(smooth: np.ndarray, dpi: int) -> np.ndarray:
    """The pixels of ``smooth``, the blurred colour strip of a band cut, that are a light streak:
    the streak columns where they hold a candidate, and the pixels that are not backing next to
    them, one each side, in those rows."""
    backing = backing_mask(smooth)
    offset = _offset_px(dpi)
    if smooth.shape[1] <= 2 * offset:
        return np.zeros(backing.shape, dtype=bool)  # no room for backing on both sides
    candidates, beside = _candidates(smooth, backing, offset)
    columns = _narrow_runs(_columns(candidates, beside, dpi), offset)
    if not columns.any():
        return np.zeros(backing.shape, dtype=bool)
    grown = columns.copy()
    grown[1:] |= columns[:-1]
    grown[:-1] |= columns[1:]
    rows = candidates[:, columns].any(axis=1)
    return (candidates & columns) | (grown & rows[:, None] & ~backing)


def crossed_pixels(smooth: np.ndarray, dpi: int) -> np.ndarray:
    """The pixels of ``smooth`` that are not to count as backing though they may look it, because
    something crosses the streak there."""
    raise NotImplementedError
