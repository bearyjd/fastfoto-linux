"""A thin light streak down the scanner's backing band is the scanner's, not content.

A fleck on the scanner's glass or backing prints as a faint light vertical line down the band, a
pixel or two wide and 12 to 15 levels brighter than the backing. By colour it is not backing, so
the last check of a band cut (see ``guard``) found something in the strip and cancelled the cut;
and where the line splits the band, the far part may reach neither a side of the strip (a wedge of
pad is there) nor its first row (shadow tone is there), and is no longer backing either.

In the strip of a band cut a pixel can be a streak's when it is not backing, backing lies
``STREAK_MAX_MM`` to its left and to its right (rounded up to whole pixels), it is at least
``STREAK_LIGHTER`` levels brighter, in every channel, than both of those two neighbours, and its
blue minus red is within ``STREAK_TINT`` of the backing's: the scanner's streak keeps the tint of
the backing it lies on, a pink, yellow, cream or grey line does not. A column is a streak's when
that holds in ``STREAK_SHARE`` of the rows that have backing on both sides of it, and those rows
are ``STREAK_MIN_MM`` tall in all. The width follows from the neighbours: a line has backing
within 0.3 mm of each of its pixels only if it is up to about twice that wide, so with its blurred
edge a streak may be a little wider than 0.3 mm; a run of streak columns wider than the offset is
none (a line that leans across the band meets one column after the other). The streak and its
blurred edge, one pixel each side in the same rows, count as backing before it is judged whether
the backing joins a side, so the line joins the parts of the band it splits.

Where a mark crosses the streak, in the rows where its neighbours are not both backing, the blur
of the mark with the streak can look like backing; those pixels, the streak's and the pixel each
side, are not backing, so that the mark stays whole and is not cut into dust-sized pieces.

Only a lighter line is forgiven: ink darkens, so a dark streak still keeps the strip, and so do a
light line wider than that, one over under ``STREAK_SHARE`` of the rows, and one that leans. Below
the resolution where two pixels are wider than ``STREAK_MAX_MM`` (170 dpi) a pixel is too coarse to
tell a streak from a line, and the rule is off. A blank slip of the backing's colour that touches a
streak is taken for the band, as one that touches the band is; a slip with anything on it is not.
"""

import math
from dataclasses import dataclass

import numpy as np

from fastfoto_linux.documents.band import backing_mask
from fastfoto_linux.documents.units import MM_PER_INCH
from fastfoto_linux.pipeline.crop import BACKGROUND_PRIOR_RGB

STREAK_MAX_MM = 0.3  # backing lies this far to each side of a streak's pixel (whole pixels, up)
STREAK_LIGHTER = 4.0  # levels brighter, in every channel, than both of the two neighbours
STREAK_SHARE = 0.9  # of the rows that have backing on both sides of the column
STREAK_MIN_MM = 3.0  # and those rows are at least this tall in all (a band is 3 mm or more)
STREAK_TINT = 12.0  # blue minus red is within this of the backing's
STREAK_MIN_WIDTH_PX = 2  # a streak is a pixel plus its blur; wider than STREAK_MAX_MM: rule off
BACKING_TINT = BACKGROUND_PRIOR_RGB[2] - BACKGROUND_PRIOR_RGB[0]  # blue minus red: 17


@dataclass(frozen=True)
class _Streak:
    """What was found in a strip: its columns, the pixels that could be a streak's in them, the
    pixels with backing on both sides, and the pixels that are backing by colour."""

    columns: np.ndarray
    candidates: np.ndarray
    beside: np.ndarray
    backing: np.ndarray


def _rule_is_off(dpi: int) -> bool:
    """Two pixels are wider than ``STREAK_MAX_MM`` below 170 dpi (at 200 dpi: 0.25 mm)."""
    return STREAK_MIN_WIDTH_PX * MM_PER_INCH / dpi > STREAK_MAX_MM


def _offset_px(dpi: int) -> int:
    """``STREAK_MAX_MM`` in whole pixels, rounded up."""
    return math.ceil(STREAK_MAX_MM * dpi / MM_PER_INCH)


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
    left_backing, right_backing = _beside(backing, offset, False)
    left, right = _beside(smooth, offset, 0.0)
    beside = left_backing & right_backing
    lighter = (smooth >= np.maximum(left, right) + STREAK_LIGHTER).all(axis=2)
    tinted = np.abs(smooth[..., 2] - smooth[..., 0] - BACKING_TINT) <= STREAK_TINT
    return ~backing & beside & lighter & tinted, beside


def _columns(candidates: np.ndarray, beside: np.ndarray, dpi: int) -> np.ndarray:
    """The columns where enough rows with backing on both sides hold a candidate."""
    support = beside.sum(axis=0)
    long_enough = support >= STREAK_MIN_MM * dpi / MM_PER_INCH
    return long_enough & (candidates.sum(axis=0) >= STREAK_SHARE * support)


def _runs(columns: np.ndarray) -> list[tuple[int, int]]:
    """The first column and the column after the last of every run of neighbouring ``columns``."""
    edges = np.flatnonzero(np.diff(columns.astype(np.int8), prepend=0, append=0))
    return list(zip(edges[::2].tolist(), edges[1::2].tolist(), strict=True))


def _narrow_runs(columns: np.ndarray, limit: int) -> np.ndarray:
    """``columns`` without the runs of more than ``limit`` neighbouring columns: a line that
    leans across the band meets one column after the other, and a light bar is no streak."""
    narrow = columns.copy()
    for start, end in _runs(columns):
        if end - start > limit:
            narrow[start:end] = False
    return narrow


def _find(smooth: np.ndarray, dpi: int) -> _Streak | None:
    """The streak in ``smooth``, the blurred colour strip of a band cut, or None: the rule is off
    at this resolution, there is no room for backing on both sides, or no column is a streak."""
    offset = _offset_px(dpi)
    if _rule_is_off(dpi) or smooth.shape[1] <= 2 * offset:
        return None
    backing = backing_mask(smooth)
    candidates, beside = _candidates(smooth, backing, offset)
    columns = _narrow_runs(_columns(candidates, beside, dpi), offset)
    return _Streak(columns, candidates, beside, backing) if columns.any() else None


def _widened(mask: np.ndarray) -> np.ndarray:
    """``mask`` and the pixel each side of it (the last axis): the blurred edge."""
    wide = mask.copy()
    wide[..., 1:] |= mask[..., :-1]
    wide[..., :-1] |= mask[..., 1:]
    return wide


def _streak_pixels(streak: _Streak) -> np.ndarray:
    """The streak columns where they hold a candidate, and the pixels that are not backing next
    to them, one each side, in those rows."""
    rows = streak.candidates[:, streak.columns].any(axis=1)
    edge = _widened(streak.columns) & rows[:, None] & ~streak.backing
    return (streak.candidates & streak.columns) | edge


def _crossed_pixels(streak: _Streak) -> np.ndarray:
    """The pixels where something lies across a streak: in a row where the neighbours of one of
    its columns are not both backing and that column is backing by colour (the blur of a mark with
    the streak), the whole run of columns and the pixel each side of it."""
    broken = streak.columns & ~streak.beside & streak.backing
    for start, end in _runs(streak.columns):
        broken[:, start:end] = broken[:, start:end].any(axis=1, keepdims=True)
    return _widened(broken)


def streak_pixels(smooth: np.ndarray, dpi: int) -> np.ndarray:
    """The pixels of ``smooth``, the blurred colour strip of a band cut, that are a light streak:
    the streak columns where they hold a candidate, and the pixels that are not backing next to
    them, one each side, in those rows."""
    streak = _find(smooth, dpi)
    return np.zeros(smooth.shape[:2], dtype=bool) if streak is None else _streak_pixels(streak)


def crossed_pixels(smooth: np.ndarray, dpi: int) -> np.ndarray:
    """The pixels of ``smooth`` that are not to count as backing though they may look it, because
    something crosses the streak there: in the rows where the streak's neighbours are not both
    backing, its pixels that are backing by colour (the blur of a mark with the streak), and the
    pixel each side of them."""
    streak = _find(smooth, dpi)
    return np.zeros(smooth.shape[:2], dtype=bool) if streak is None else _crossed_pixels(streak)


def with_streak(backing: np.ndarray, smooth: np.ndarray, dpi: int) -> np.ndarray:
    """``backing``, the backing mask of the blurred colour strip ``smooth`` of a band cut, with the
    streak counted as backing and the pixels a mark crosses it at taken out (``backing`` itself
    when there is no streak). ``backing`` is not changed."""
    streak = _find(smooth, dpi)
    if streak is None:
        return backing
    return (backing & ~_crossed_pixels(streak)) | _streak_pixels(streak)
