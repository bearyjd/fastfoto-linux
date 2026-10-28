"""Measure the tilt of a trimmed page of text, or say why it cannot be measured.

A projection profile on a work grid of about 100 dpi, in integers only: the ink pixels of the
grid are turned clockwise by each candidate angle and the angle whose rows hold the ink most
unevenly (the largest sum of squared row counts) wins. A coarse pass over -10 to 10 degrees
in half degrees is followed by a pass in tenths around the best. The answer is the angle, in
tenths of a degree, that straightens the page when applied clockwise (``deskew_warp``).

The estimate abstains (``SkewStatus``) rather than guess: too little ink, a photo, a best angle
at the edge of the range, a peak that is not clearly higher than the best peak far from it, text
the turn would push out of the frame, or a tilt under 0.3 degrees. Every constant is in
``deskew_tables``. Calibration is on generated pages only; nothing here claims an accuracy on
real scans.
"""

import threading
from dataclasses import dataclass
from enum import StrEnum

import cv2
import numpy as np

from fastfoto_linux.documents import deskew_tables as tables
from fastfoto_linux.documents.cleanup import work_too_large
from fastfoto_linux.documents.errors import stop_if_cancelled
from fastfoto_linux.documents.loader import LoadedPage
from fastfoto_linux.documents.modes import ColourMode
from fastfoto_linux.photo_edits.straighten import TRIG_BITS, trig


class SkewStatus(StrEnum):
    LOW_DPI = "low_dpi"
    TOO_LARGE = "too_large"
    LITTLE_INK = "little_ink"
    NOT_TEXT = "not_text"
    EDGE = "edge"
    UNSURE = "unsure"
    WOULD_CLIP = "would_clip"
    LEVEL = "level"
    ESTIMATED = "estimated"
    CROPPED = "cropped"  # the page has a crop and seeding leaves it alone (see deskew_draft)
    NO_SOURCE = "no_source"  # the draft has no folder to read the page from


@dataclass(frozen=True)
class SkewEstimate:
    """The outcome: ``tenths`` is set only for ``ESTIMATED`` (else 0). ``separation_pct`` is the
    best score far from the peak as a percentage of the peak (0 when it was not computed)."""

    status: SkewStatus
    tenths: int = 0
    separation_pct: int = 0


def _work_ink(page: LoadedPage) -> tuple[np.ndarray, np.ndarray, tuple[int, int]]:
    """The ink pixel coordinates (ys, xs, int64) of the work grid and the grid shape."""
    height, width = page.pixels.shape[:2]
    grey = (
        cv2.cvtColor(page.pixels, cv2.COLOR_RGB2GRAY)
        if page.kind is ColourMode.COLOUR
        else page.pixels
    )
    step = max(1, page.dpi // tables.WORK_DPI)
    small = cv2.resize(grey, (width // step, height // step), interpolation=cv2.INTER_AREA)
    otsu, _ = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    ink = small < min(int(otsu), tables.INK_MAX_LEVEL)
    ys, xs = np.nonzero(ink)
    return ys.astype(np.int64), xs.astype(np.int64), ink.shape


def _score(ys: np.ndarray, xs: np.ndarray, tenths: int) -> int:
    cos, sin = trig(tenths)
    rows = (ys * cos + xs * sin) >> TRIG_BITS
    hist = np.bincount(rows - rows.min()).astype(np.int64)
    return int((hist * hist).sum())


def _best(scores: dict[int, int]) -> int:
    """The angle with the top score; ties go to the smaller |angle|, then the negative one."""
    best, top = 0, -1
    for angle in sorted(scores, key=lambda a: (abs(a), a)):
        if scores[angle] > top:
            best, top = angle, scores[angle]
    return best


def _clips(ys: np.ndarray, xs: np.ndarray, tenths: int, shape: tuple[int, int]) -> bool:
    """Whether turning the points clockwise by ``tenths`` puts one outside the frame."""
    cos, sin = trig(tenths)
    new_x = (xs * cos - ys * sin) >> TRIG_BITS
    new_y = (xs * sin + ys * cos) >> TRIG_BITS
    slack = tables.CLIP_SLACK_PX
    low_x, low_y = -(shape[1] // 2) - slack, -(shape[0] // 2) - slack
    high_x, high_y = shape[1] - 1 - shape[1] // 2 + slack, shape[0] - 1 - shape[0] // 2 + slack
    return bool(
        (new_x < low_x).any()
        or (new_x > high_x).any()
        or (new_y < low_y).any()
        or (new_y > high_y).any()
    )


def estimate_skew(page: LoadedPage, *, cancel: threading.Event | None = None) -> SkewEstimate:
    """The tilt of ``page`` (already trimmed), or the reason it is not measured. Raises
    DocumentCancelledError when ``cancel`` is set (checked before each pass)."""
    height, width = page.pixels.shape[:2]
    if page.dpi < tables.MIN_DPI:
        return SkewEstimate(SkewStatus.LOW_DPI)
    if work_too_large(height, width, page.dpi):
        return SkewEstimate(SkewStatus.TOO_LARGE)
    stop_if_cancelled(cancel, "measuring the tilt of a page")
    ys, xs, shape = _work_ink(page)
    if ys.size < tables.MIN_INK_POINTS:
        return SkewEstimate(SkewStatus.LITTLE_INK)
    if ys.size * 100 > tables.MAX_INK_PCT * shape[0] * shape[1]:
        return SkewEstimate(SkewStatus.NOT_TEXT)
    ys, xs = ys - shape[0] // 2, xs - shape[1] // 2
    if ys.size > tables.MAX_POINTS:
        stride = -(-ys.size // tables.MAX_POINTS)
        ys, xs = ys[::stride], xs[::stride]
    limit, step = tables.MAX_TENTHS, tables.COARSE_STEP
    coarse = {a: _score(ys, xs, a) for a in range(-limit, limit + 1, step)}
    best = _best(coarse)
    if abs(best) == limit:
        return SkewEstimate(SkewStatus.EDGE)
    stop_if_cancelled(cancel, "measuring the tilt of a page")
    fine = dict(coarse)
    for angle in range(best - step, best + step + 1):
        if -limit <= angle <= limit and angle not in fine:
            fine[angle] = _score(ys, xs, angle)
    estimate = _best(fine)
    peak = fine[estimate]
    far = max(
        score
        for angle, score in coarse.items()
        if abs(angle - estimate) >= tables.SEPARATION_TENTHS
    )
    return _verdict(ys, xs, shape, estimate, (far, peak))


def _verdict(
    ys: np.ndarray, xs: np.ndarray, shape: tuple[int, int], estimate: int, scores: tuple[int, int]
) -> SkewEstimate:
    """The last three abstains and the answer, for the best angle and (far, peak) scores."""
    far, peak = scores
    separation = far * 100 // peak
    if far * 100 >= tables.SEPARATION_PCT * peak:
        return SkewEstimate(SkewStatus.UNSURE, 0, separation)
    if _clips(ys, xs, estimate, shape):
        return SkewEstimate(SkewStatus.WOULD_CLIP, 0, separation)
    if abs(estimate) < tables.MIN_TENTHS:
        return SkewEstimate(SkewStatus.LEVEL, 0, separation)
    return SkewEstimate(SkewStatus.ESTIMATED, estimate, separation)
