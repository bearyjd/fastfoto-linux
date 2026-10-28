"""Measure the tilt of a trimmed page of text, or say why it cannot be measured.

A projection profile on a work grid of about 100 dpi, in integers only: the ink pixels of the
grid are turned clockwise by each candidate angle and the angle whose rows hold the ink most
unevenly (the largest sum of squared row counts) wins. Every tenth within -10 to 10 degrees
is scored, and every degree out to 45 (a second tilt there counts against the confidence). The
answer is the best angle within 10 degrees, in tenths of a degree, that straightens the page when
applied clockwise (``deskew_warp``).

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


def _work_grid(page: LoadedPage) -> np.ndarray:
    """The grey page on a work grid of about ``WORK_DPI`` (the step ``dpi // 100`` was chosen at
    300 dpi; it is kept within the page like ``cleanup``'s)."""
    height, width = page.pixels.shape[:2]
    grey = (
        cv2.cvtColor(page.pixels, cv2.COLOR_RGB2GRAY)
        if page.kind is ColourMode.COLOUR
        else page.pixels
    )
    step = max(1, min(page.dpi // tables.WORK_DPI, height, width))
    return cv2.resize(grey, (width // step, height // step), interpolation=cv2.INTER_AREA)


def _centred(mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    ys, xs = np.nonzero(mask)
    return ys.astype(np.int64) - mask.shape[0] // 2, xs.astype(np.int64) - mask.shape[1] // 2


def _extremes(mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The first and last marked pixel of every row, centred: the corners of the convex hull of
    the marks are among them, so they bound every turn of the marks."""
    rows = np.flatnonzero(mask.any(axis=1))
    first = mask[rows].argmax(axis=1)
    last = mask.shape[1] - 1 - mask[rows, ::-1].argmax(axis=1)
    ys = np.concatenate([rows, rows]).astype(np.int64) - mask.shape[0] // 2
    xs = np.concatenate([first, last]).astype(np.int64) - mask.shape[1] // 2
    return ys, xs


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


def _scores(ys: np.ndarray, xs: np.ndarray, cancel: threading.Event | None) -> dict[int, int]:
    """The score of every tenth within the applied range, then of every ``OUTER_STEP`` tenths out
    to ``OUTER_MAX_TENTHS`` (a second tilt there counts against the confidence)."""
    limit = tables.MAX_TENTHS
    scores = {a: _score(ys, xs, a) for a in range(-limit, limit + 1)}
    stop_if_cancelled(cancel, "measuring the tilt of a page")
    for a in range(-tables.OUTER_MAX_TENTHS, tables.OUTER_MAX_TENTHS + 1, tables.OUTER_STEP):
        if abs(a) > limit:
            scores[a] = _score(ys, xs, a)
    return scores


def estimate_skew(page: LoadedPage, *, cancel: threading.Event | None = None) -> SkewEstimate:
    """The tilt of ``page`` (already trimmed), or the reason it is not measured. Raises
    DocumentCancelledError when ``cancel`` is set (checked before each pass)."""
    height, width = page.pixels.shape[:2]
    if page.dpi < tables.MIN_DPI:
        return SkewEstimate(SkewStatus.LOW_DPI)
    if work_too_large(height, width, page.dpi):
        return SkewEstimate(SkewStatus.TOO_LARGE)
    stop_if_cancelled(cancel, "measuring the tilt of a page")
    small = _work_grid(page)
    otsu, _ = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    ink = small <= min(int(otsu), tables.INK_MAX_LEVEL)  # <=: a 0/255 page has Otsu level 0
    if int(ink.sum()) < tables.MIN_INK_POINTS:
        return SkewEstimate(SkewStatus.LITTLE_INK)
    if int(ink.sum()) * 100 > tables.MAX_INK_PCT * ink.size:
        return SkewEstimate(SkewStatus.NOT_TEXT)
    ys, xs = _centred(ink)
    if ys.size > tables.MAX_POINTS:
        stride = -(-ys.size // tables.MAX_POINTS)
        ys, xs = ys[::stride], xs[::stride]
    scores = _scores(ys, xs, cancel)
    estimate = _best({a: s for a, s in scores.items() if abs(a) <= tables.MAX_TENTHS})
    if abs(estimate) >= tables.MAX_TENTHS:
        return SkewEstimate(SkewStatus.EDGE)
    peak = scores[estimate]
    far = max(s for a, s in scores.items() if abs(a - estimate) >= tables.SEPARATION_TENTHS)
    content = ink | (small < int(np.median(small)) - tables.CONTENT_DELTA)
    return _verdict(_extremes(content), ink.shape, estimate, (far, peak))


def _verdict(
    corners: tuple[np.ndarray, np.ndarray],
    shape: tuple[int, int],
    estimate: int,
    scores: tuple[int, int],
) -> SkewEstimate:
    """The last three abstains and the answer, for the best angle and (far, peak) scores. The
    clip check uses the extremes of all the content, not the thinned ink that was scored."""
    far, peak = scores
    separation = far * 100 // peak
    if far * 100 >= tables.SEPARATION_PCT * peak:
        return SkewEstimate(SkewStatus.UNSURE, 0, separation)
    if _clips(*corners, estimate, shape):
        return SkewEstimate(SkewStatus.WOULD_CLIP, 0, separation)
    if abs(estimate) < tables.MIN_TENTHS:
        return SkewEstimate(SkewStatus.LEVEL, 0, separation)
    return SkewEstimate(SkewStatus.ESTIMATED, estimate, separation)
