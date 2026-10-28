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


def _work_grid(page: LoadedPage) -> tuple[np.ndarray, np.ndarray]:
    """The grey page on a work grid of about ``WORK_DPI`` (the step ``dpi // 100`` was chosen at
    300 dpi; it is kept within the page like ``cleanup``'s), and the darkest full-resolution pixel
    of each grid cell (the cells take the rows and columns left over), so that a one pixel stroke
    is not averaged away."""
    height, width = page.pixels.shape[:2]
    grey = (
        cv2.cvtColor(page.pixels, cv2.COLOR_RGB2GRAY)
        if page.kind is ColourMode.COLOUR
        else page.pixels
    )
    step = max(1, min(page.dpi // tables.WORK_DPI, height, width))
    rows, cols = height // step, width // step
    small = cv2.resize(grey, (cols, rows), interpolation=cv2.INTER_AREA)
    by_row = np.minimum.reduceat(grey, np.arange(rows) * step, axis=0)
    return small, np.minimum.reduceat(by_row, np.arange(cols) * step, axis=1)


def _centred(mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    ys, xs = np.nonzero(mask)
    return ys.astype(np.int64) - mask.shape[0] // 2, xs.astype(np.int64) - mask.shape[1] // 2


def _extremes(mask: np.ndarray, step: int, frame: tuple[int, int]) -> np.ndarray:
    """The corners (x, y, in full-resolution pixel edges) of the first and the last marked cell of
    every row of ``mask``, one row per corner. A cell covers ``step`` pixels each way, the last
    row and column of cells also the pixels left over to the frame's end (height, width). Every
    corner of the convex hull of the cells is one of these, so they bound every turn of the
    content."""
    height, width = frame
    rows = np.flatnonzero(mask.any(axis=1))
    ends = np.concatenate(
        [mask[rows].argmax(axis=1), mask.shape[1] - 1 - mask[rows, ::-1].argmax(axis=1)]
    )
    cells = np.concatenate([rows, rows])
    y0, x0 = cells.astype(np.int64) * step, ends.astype(np.int64) * step
    y1 = np.where(cells == mask.shape[0] - 1, height, y0 + step)
    x1 = np.where(ends == mask.shape[1] - 1, width, x0 + step)
    return np.stack([np.stack([x, y], axis=1) for x in (x0, x1) for y in (y0, y1)]).reshape(-1, 2)


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


def _clips(corners: np.ndarray, tenths: int, frame: tuple[int, int]) -> bool:
    """Whether turning the content clockwise by ``tenths`` puts any corner of a content cell
    outside the frame, with no allowance and no rounding.

    The corners are pixel edges, so the frame is ``[0, width] x [0, height]`` and the turn is about
    its centre, as in ``deskew_warp``. In half-pixel units about the centre a corner is
    ``u = 2x - width``, ``v = 2y - height`` and the frame is ``|u| <= width``, ``|v| <= height``.
    The turned corner is ``(u cos - v sin, u sin + v cos)``; with cos and sin the integers of
    ``straighten.trig`` (scaled by 2**24, the very values the warp divides by 2**24) the products
    are exact in int64 (``|u|, |v| < 2**18``, so below 2**43), and they are compared with the frame
    scaled by 2**24. Nothing is floored or rounded, so the content, which lies inside its cells,
    cannot leave the frame unless a corner does."""
    height, width = frame
    cos, sin = trig(tenths)
    u = 2 * corners[:, 0] - width
    v = 2 * corners[:, 1] - height
    new_u = u * cos - v * sin
    new_v = u * sin + v * cos
    return bool(
        (np.abs(new_u) > (width << TRIG_BITS)).any()
        or (np.abs(new_v) > (height << TRIG_BITS)).any()
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
    stop_if_cancelled(cancel, "measuring the tilt of a page")
    outer = sorted((a for a in scores if abs(a) > limit), key=lambda a: -scores[a])
    for a in outer[: tables.REFINED_PEAKS]:  # a narrow peak can fall between two samples
        for near in range(a - tables.OUTER_STEP + 1, a + tables.OUTER_STEP):
            if near not in scores:
                scores[near] = _score(ys, xs, near)
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
    small, darkest = _work_grid(page)
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
    content = ink | (darkest < int(np.median(small)) - tables.CONTENT_DELTA)
    step = max(1, min(page.dpi // tables.WORK_DPI, height, width))
    corners = _extremes(content, step, (height, width))
    return _verdict(corners, (height, width), estimate, (far, peak))


def _verdict(
    corners: np.ndarray,
    frame: tuple[int, int],
    estimate: int,
    scores: tuple[int, int],
) -> SkewEstimate:
    """The last three abstains and the answer, for the best angle and (far, peak) scores. The
    clip check uses the extremes of all the content, not the thinned ink that was scored."""
    far, peak = scores
    separation = far * 100 // peak
    if far * 100 >= tables.SEPARATION_PCT * peak:
        return SkewEstimate(SkewStatus.UNSURE, 0, separation)
    if _clips(corners, estimate, frame):
        return SkewEstimate(SkewStatus.WOULD_CLIP, 0, separation)
    if abs(estimate) < tables.MIN_TENTHS:
        return SkewEstimate(SkewStatus.LEVEL, 0, separation)
    return SkewEstimate(SkewStatus.ESTIMATED, estimate, separation)
