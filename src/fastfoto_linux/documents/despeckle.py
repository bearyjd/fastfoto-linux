"""Despeckle: remove small, isolated black specks from a black and white page, exactly.

A component (8-connected black pixels) is removed when its box is at most ``s`` pixels (0.30 mm)
on each side, no other ink lies within ``g`` pixels (2.5 mm) of its box, and no pixel of it is
colourful in the colour source (a red dot is deliberate). Everything is integer arithmetic on
full-resolution pixels. Removal repeats until a round removes nothing, because the box test is
not symmetric: removing an isolated Y can isolate X.

Why it is exact in bands: a band decides the components whose top row it owns and labels the
rows ``[top - g, bottom + s + g)``. A decided candidate and its guard window lie wholly inside
those rows; a component cut at the lower edge is at least ``s + g + 1`` rows tall, so the size
test rejects it. The banded result therefore equals the whole-page result, and no decision
depends on a label number. All removals of a round are applied only after every band was
judged, so the result does not depend on the band order either.

Memory: the labelling of a band is bounded by the band whatever the pattern (it runs on one
thread, see ``_one_thread``); the arrays that span the page grow with it, and a page of more
than ``MAX_DESPECKLE_PIXELS`` pixels is left as it is.

Why it cannot remove punctuation: a mark over 0.30 mm on either side is kept by size, and a
mark of 0.30 mm or less belongs to text small enough that a neighbouring glyph lies within
2.5 mm, which keeps it by isolation. Limits: an isolated deliberate dot over 2.5 mm from any
ink, and dotted leaders spaced over 2.5 mm, are removed; dust over 0.30 mm is kept.
"""

import contextlib
import threading
from collections.abc import Iterator
from enum import StrEnum
from typing import NamedTuple

import cv2
import numpy as np

from fastfoto_linux.documents.cleanup import work_too_large
from fastfoto_linux.documents.despeckle_tables import (
    BAND_ROWS,
    CONNECTIVITY,
    MAX_BAND_PIXELS,
    MAX_DESPECKLE_PIXELS,
    MAX_ROUNDS,
    MAX_SPECKS,
    MIN_DPI,
    SPECK_CHROMA,
    guard_px,
    speck_px,
)
from fastfoto_linux.documents.errors import DocumentCancelledError


class DespeckleStatus(StrEnum):
    """What despeckle did to a page (the first that applies). Only ``APPLIED`` changes it."""

    OFF = "off"
    NOT_BW = "not_bw"
    LOW_DPI = "low_dpi"
    TOO_LARGE = "too_large"
    BUSY = "busy"
    UNSTABLE = "unstable"
    NONE = "none"
    APPLIED = "applied"


class DespeckleResult(NamedTuple):
    """The status, the new white mask when it is ``APPLIED`` (else None: the plain render is the
    answer) and the number of components removed."""

    status: DespeckleStatus
    pixels: np.ndarray | None
    removed: int


class _Sizes(NamedTuple):
    cap: int  # s: the largest side of a speck, in pixels
    guard: int  # g: the clear space around its box, in pixels


class _Found(NamedTuple):
    rows: np.ndarray
    cols: np.ndarray
    count: int


def _chroma_mask(source: np.ndarray | None) -> np.ndarray | None:
    """Where the colour source is colourful, or None for a grey or missing source."""
    if source is None or source.ndim != 3:  # noqa: PLR2004 - HxWx3
        return None
    return (source.max(axis=2) - source.min(axis=2)) >= SPECK_CHROMA


class _Pin:
    """How many labellings hold OpenCV's thread count at one, and the count to give back."""

    lock = threading.Lock()
    depth = 0
    saved = 0


@contextlib.contextmanager
def _one_thread() -> Iterator[None]:
    """OpenCV labels on one thread inside the block. With many threads its labelling of a dense
    pattern (every other pixel black) allocated about a gigabyte for one band of an A4 page; on
    one thread the peak is the band's own arrays. The count is process-wide, so overlapping
    blocks (several threads despeckling) share one pin: the first saves the count and sets one,
    the last gives it back, and every labelling in between sees one thread. Other code that
    labels at the same moment on other threads runs on one thread too (slower, not wrong), and
    code that changes the count while a block is open has its change undone at the end."""
    with _Pin.lock:
        if _Pin.depth == 0:
            _Pin.saved = cv2.getNumThreads()
            cv2.setNumThreads(1)
        _Pin.depth += 1
    try:
        yield
    finally:
        with _Pin.lock:
            _Pin.depth -= 1
            if _Pin.depth == 0:
                cv2.setNumThreads(_Pin.saved)


def _band(
    ink: np.ndarray, chroma: np.ndarray | None, rows: tuple[int, int], sizes: _Sizes
) -> tuple[np.ndarray, np.ndarray, int]:
    """The removable pixels (rows, columns, component count) of the components that start in
    rows ``[top, bottom)``."""
    (top, bottom), (s, g) = rows, sizes
    height, width = ink.shape
    first, last = max(0, top - g), min(height, bottom + s + g)
    window = ink[first:last]
    with _one_thread():
        count, labels, stats, _ = cv2.connectedComponentsWithStats(
            window, connectivity=CONNECTIVITY, ltype=cv2.CV_32S
        )
    none = np.empty(0, dtype=np.intp)
    if count < 2:  # noqa: PLR2004 - only the background
        return none, none, 0
    left, up, wide, high, area = (stats[1:, column] for column in range(5))  # int32
    start = first + up
    ok = (wide <= s) & (high <= s) & (start >= top) & (start < bottom)
    if not ok.any():
        return none, none, 0
    integral = cv2.integral(window, sdepth=cv2.CV_32S)  # sums stay under MAX_BAND_PIXELS
    r0, r1 = np.maximum(0, up - g), np.minimum(last - first, up + high + g)
    c0, c1 = np.maximum(0, left - g), np.minimum(width, left + wide + g)
    inside = integral[r1, c1] - integral[r0, c1] - integral[r1, c0] + integral[r0, c0]
    ok &= inside == area
    wanted = np.zeros(count, dtype=bool)
    wanted[1:] = ok
    if chroma is not None:
        wanted[np.unique(labels[chroma[first:last]])] = False
    if not wanted.any():
        return none, none, 0
    rows, cols = np.nonzero(wanted[labels])
    return rows + first, cols, int(wanted.sum())


def _band_rows(width: int, sizes: _Sizes) -> int:
    """The rows a band owns: ``BAND_ROWS``, fewer when the page is wide enough that the window
    (those rows and the guard rows around them) would pass ``MAX_BAND_PIXELS``."""
    guard_rows = sizes.cap + 2 * sizes.guard
    return max(1, min(BAND_ROWS, MAX_BAND_PIXELS // width - guard_rows))


def abstain_status(height: int, width: int, dpi: int) -> DespeckleStatus | None:
    """Why a page of this size and resolution is left alone before any pixel is looked at, or
    None. Cheap and allocation free: ``render_page`` asks before it builds the page's mask."""
    sizes = _Sizes(speck_px(dpi), guard_px(dpi))
    if dpi < MIN_DPI or sizes.cap < 1:
        return DespeckleStatus.LOW_DPI
    narrowest = min(height, 1 + sizes.cap + 2 * sizes.guard) * width  # one owned row's window
    if (
        height * width > MAX_DESPECKLE_PIXELS
        or work_too_large(height, width, dpi)
        or narrowest > MAX_BAND_PIXELS
    ):
        return DespeckleStatus.TOO_LARGE
    return None


def _removable(
    ink: np.ndarray,
    chroma: np.ndarray | None,
    sizes: _Sizes,
    cancel: threading.Event | None,
    limit: int | None,
) -> _Found | None:
    """Every removable pixel of the page, judged against ``ink`` as it is. None: more than
    ``limit`` components are removable."""
    rows: list[np.ndarray] = []
    cols: list[np.ndarray] = []
    total = 0
    step = _band_rows(ink.shape[1], sizes)
    for top in range(0, ink.shape[0], step):
        if cancel is not None and cancel.is_set():
            raise DocumentCancelledError("despeckle cancelled")
        band_rows, band_cols, count = _band(ink, chroma, (top, top + step), sizes)
        rows.append(band_rows)
        cols.append(band_cols)
        total += count
        if limit is not None and total > limit:
            return None
    return _Found(np.concatenate(rows), np.concatenate(cols), total)


def despeckle_white(
    white: np.ndarray,
    dpi: int,
    *,
    source: np.ndarray | None = None,
    cancel: threading.Event | None = None,
) -> DespeckleResult:
    """``white`` (HxW bool, True where white) without its small isolated specks.

    ``source`` is the RGB page it was made from, if any (a colourful component is kept). The
    input is not modified. Raises DocumentCancelledError when ``cancel`` is set before a band.
    """
    abstain = abstain_status(white.shape[0], white.shape[1], dpi)
    if abstain is not None:
        return DespeckleResult(abstain, None, 0)
    sizes = _Sizes(speck_px(dpi), guard_px(dpi))
    chroma = _chroma_mask(source)
    current, total = white, 0
    for round_number in range(MAX_ROUNDS + 1):
        found = _removable(
            (~current).astype(np.uint8),
            chroma,
            sizes,
            cancel,
            MAX_SPECKS if round_number == 0 else None,
        )
        if found is None:
            return DespeckleResult(DespeckleStatus.BUSY, None, 0)
        if found.count == 0:
            break
        if round_number == MAX_ROUNDS:
            return DespeckleResult(DespeckleStatus.UNSTABLE, None, 0)
        current = current.copy() if current is white else current
        current[found.rows, found.cols] = True
        total += found.count
    if total == 0:
        return DespeckleResult(DespeckleStatus.NONE, None, 0)
    return DespeckleResult(DespeckleStatus.APPLIED, current, total)
