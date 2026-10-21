"""Paper cleanup: lighten the paper tone of a grey or colour page, and nothing else.

Off by default. The paper level of each spot comes from a low-resolution estimate of the
background (the brightest pixel of each block, closed over 10 mm so no text stroke is left in it,
then smoothed). A pixel is lightened by a capped gain that depends on that background and on how
far the pixel is from it: ink, anything dark against its paper (a pencil stroke, a stamp, a
rule), is not touched, and the gain never makes a pixel darker. Photographs are found by cells
that hold many mid-light pixels and are left alone with a soft rim, coloured marks are left
alone by their chroma, and a colour page on coloured stock is left alone as a whole when it is
written in colour (in grey the hue is gone, so it is cleaned). A page whose paper is dark is
left alone. Every step is integer arithmetic (see ``cleanup_tables``), so the same page always
gives the same bytes, and the full-resolution passes run in bands that give the same pixels as
one pass over the page.

The page is turned before it is cleaned (the work grid is anchored at the top left), and
analysis (blank, holes, colour) never sees the cleaned pixels: this runs only when a page is
rendered for the PDF or a preview.
"""

import logging
import threading
from collections.abc import Iterator
from enum import StrEnum
from typing import TYPE_CHECKING, NamedTuple

import cv2
import numpy as np

from fastfoto_linux.documents.bilevel import _odd
from fastfoto_linux.documents.cleanup_tables import (
    BAND_ROWS,
    BG_SMOOTH_MM,
    BG_WINDOW_MM,
    CELL_MM,
    INK_HI_PCT,
    INK_LO_PCT,
    PAPER_MIN_LEVEL,
    PAPER_PCT,
    Q_BITS,
    STOCK_CHROMA,
    TONAL_PCT,
    TONAL_SHARE_PCT,
    Q,
    channel_caps,
    chroma_weights,
    tone_table,
)
from fastfoto_linux.documents.errors import DocumentCancelledError
from fastfoto_linux.documents.marks import WORK_DPI
from fastfoto_linux.documents.modes import CleanupPolicy, ColourMode
from fastfoto_linux.documents.units import mm_to_px

if TYPE_CHECKING:
    from fastfoto_linux.documents.draft import DocumentDraft, PageAnalysis

logger = logging.getLogger(__name__)


class CleanupStatus(StrEnum):
    """What cleanup did to a page (the first that applies)."""

    OFF = "off"
    BW = "bw"  # black and white is never cleaned
    DARK = "dark"  # the paper is darker than PAPER_MIN_LEVEL
    NO_PAPER = "no_paper"  # a colour page with no pixel that is paper
    STOCK = "stock"  # coloured paper, written in colour: the hue is kept as it is
    APPLIED = "applied"


class CleanupResult(NamedTuple):
    """The status, and the cleaned pixels when it is ``APPLIED`` (else None: render as usual)."""

    status: CleanupStatus
    pixels: np.ndarray | None


def page_cleanup(draft: "DocumentDraft", page: "PageAnalysis") -> CleanupPolicy:
    """The page's own override, else the document's level."""
    edit = draft.edits.get(page.number)
    return edit.cleanup if edit is not None and edit.cleanup is not None else draft.cleanup


def box_mean(values: np.ndarray, size: int) -> np.ndarray:
    """The mean over a ``size`` x ``size`` window (odd), rounded half up, edges copied; int64."""
    pad = size // 2
    padded = np.pad(values.astype(np.int64), pad, mode="edge")
    total = np.zeros((padded.shape[0] + 1, padded.shape[1] + 1), np.int64)
    np.cumsum(np.cumsum(padded, axis=0), axis=1, out=total[1:, 1:])
    window = (
        total[size:, size:] - total[:-size, size:] - total[size:, :-size] + total[:-size, :-size]
    )
    count = size * size
    return (window + count // 2) // count


class _Grid(NamedTuple):
    """The low-resolution work grid: ``f`` pixels per step, ``rows``/``cols`` map a full-resolution
    row or column to its step (the last step takes the remainder)."""

    f: int
    rows: np.ndarray
    cols: np.ndarray


def _grid(height: int, width: int, dpi: int) -> _Grid:
    f = max(1, min(dpi // WORK_DPI, height, width))
    rows = np.minimum(np.arange(height) // f, height // f - 1)
    cols = np.minimum(np.arange(width) // f, width // f - 1)
    return _Grid(f, rows, cols)


def _background(grey: np.ndarray, dpi: int, grid: _Grid) -> np.ndarray:
    """The smoothed background, one uint8 per grid step."""
    f = grid.f
    high, wide = grey.shape[0] // f, grey.shape[1] // f
    small = grey
    if f > 1:
        small = grey[: high * f : f, : wide * f : f].copy()
        for dy in range(f):
            for dx in range(f):
                np.maximum(small, grey[dy : high * f : f, dx : wide * f : f], out=small)
    size = _odd(mm_to_px(BG_WINDOW_MM, dpi / f))
    closed = cv2.morphologyEx(
        small, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (size, size))
    )
    return box_mean(closed, _odd(mm_to_px(BG_SMOOTH_MM, dpi / f))).astype(np.uint8)


def _paper_level(smooth: np.ndarray) -> int:
    """The level that ``PAPER_PCT`` percent of the background is at or below."""
    seen = np.cumsum(np.bincount(smooth.ravel(), minlength=256))
    return int(np.searchsorted(seen, (smooth.size * PAPER_PCT + 99) // 100))


def _bands(height: int, cancel: threading.Event | None) -> Iterator[tuple[int, int]]:
    """Row bands of ``BAND_ROWS``; a cancel is honoured before each."""
    step = max(1, BAND_ROWS)
    for top in range(0, height, step):
        if cancel is not None and cancel.is_set():
            raise DocumentCancelledError("cleanup cancelled")
        yield top, min(height, top + step)


class _Layout(NamedTuple):
    """The cells that are checked for a photograph: ``cs`` grid steps wide, ``cell`` pixels, the
    last row and column of cells taking the remainder."""

    cs: int
    ch: int
    cw: int
    rows: np.ndarray  # cell row of each pixel row
    cols: np.ndarray


def _layout(height: int, width: int, dpi: int, grid: _Grid) -> _Layout:
    cs = mm_to_px(CELL_MM, dpi / grid.f)
    cell = cs * grid.f
    ch, cw = max(1, height // cell), max(1, width // cell)
    rows = np.minimum(np.arange(height) // cell, ch - 1).astype(np.int32)
    cols = np.minimum(np.arange(width) // cell, cw - 1).astype(np.int32)
    return _Layout(cs, ch, cw, rows, cols)


class _Work(NamedTuple):
    src: np.ndarray
    grey: np.ndarray
    smooth: np.ndarray
    grid: _Grid
    layout: _Layout

    @property
    def colour(self) -> bool:
        return self.src.ndim == 3  # noqa: PLR2004 - HxWx3

    def background(self, top: int, bottom: int) -> np.ndarray:
        """The background at every pixel of the rows ``top`` to ``bottom`` (uint8)."""
        return self.smooth[self.grid.rows[top:bottom]][:, self.grid.cols]


def _chroma(band: np.ndarray) -> np.ndarray:
    return band.max(axis=2) - band.min(axis=2)


def _survey(work: _Work, cancel: threading.Event | None) -> tuple[np.ndarray, np.ndarray]:
    """Pass 1: the photograph-like pixels of every cell, and (colour page) the chroma histogram
    of the pixels that are paper."""
    layout = work.layout
    counts = np.zeros(layout.ch * layout.cw, np.int64)
    chroma = np.zeros(256, np.int64)
    for top, bottom in _bands(work.grey.shape[0], cancel):
        level = work.grey[top:bottom].astype(np.int32) * 100
        back = work.background(top, bottom).astype(np.int32)
        tonal = (level > back * INK_LO_PCT) & (level < back * TONAL_PCT)
        cells = layout.rows[top:bottom, None] * layout.cw + layout.cols[None, :]
        counts += np.bincount(cells[tonal], minlength=counts.size)
        if work.colour:
            paper = level >= back * INK_HI_PCT
            chroma += np.bincount(_chroma(work.src[top:bottom])[paper], minlength=256)
    return counts.reshape(layout.ch, layout.cw), chroma


def _protection(work: _Work, counts: np.ndarray) -> np.ndarray:
    """How much of the cleanup each grid step gets, 0 (protected) to 256 (all); int32."""
    layout = work.layout
    area = np.outer(
        np.bincount(layout.rows, minlength=layout.ch), np.bincount(layout.cols, minlength=layout.cw)
    )
    cells = (counts * 100 >= TONAL_SHARE_PCT * area).astype(np.uint8)
    cells = cv2.dilate(cells, np.ones((3, 3), np.uint8))
    high, wide = work.smooth.shape
    rows = np.minimum(np.arange(high) // layout.cs, layout.ch - 1)
    cols = np.minimum(np.arange(wide) // layout.cs, layout.cw - 1)
    open_steps = np.where(cells[rows][:, cols] > 0, 0, 256)
    return box_mean(open_steps, _odd(layout.cs)).astype(np.int32)


def _apply(  # noqa: PLR0913 - what the second pass needs
    work: _Work,
    output: ColourMode,
    *,
    tone: np.ndarray,
    protection: np.ndarray,
    paper_chroma: int,
    cancel: threading.Event | None,
) -> np.ndarray:
    """Pass 2: the cleaned page, band by band."""
    grid, grey, src = work.grid, work.grey, work.src
    out = np.empty_like(src) if output is ColourMode.COLOUR else np.empty_like(grey)
    weights = chroma_weights(paper_chroma) if work.colour else None
    caps = channel_caps()
    flat = tone.ravel()
    for top, bottom in _bands(grey.shape[0], cancel):
        level, band = grey[top:bottom], src[top:bottom]
        index = (work.background(top, bottom).astype(np.uint16) << 8) | level
        gain = Q + (
            ((flat[index] - Q) * protection[grid.rows[top:bottom]][:, grid.cols] + 128) >> 8
        )
        if weights is not None:
            gain = Q + (((gain - Q) * weights[_chroma(band)] + 128) >> 8)
        if output is ColourMode.GREY:
            out[top:bottom] = np.minimum(255, (level * gain + Q // 2) >> Q_BITS)
            continue
        gain = np.minimum(gain, caps[band.max(axis=2)])
        for channel in range(3):
            out[top:bottom, :, channel] = np.minimum(
                255, (band[..., channel] * gain + Q // 2) >> Q_BITS
            )
    return out


def clean_pixels(
    src: np.ndarray,
    dpi: int,
    output: ColourMode,
    policy: CleanupPolicy,
    *,
    cancel: threading.Event | None = None,
) -> CleanupResult:
    """``src`` (HxW grey or HxWx3 RGB uint8) cleaned for ``output`` (grey or colour), or the
    reason it is not (``pixels`` is then None and the plain render is the answer). The input is
    not modified. Raises DocumentCancelledError when ``cancel`` is set before a band."""
    if policy is CleanupPolicy.OFF:
        return CleanupResult(CleanupStatus.OFF, None)
    if output is ColourMode.BW:
        return CleanupResult(CleanupStatus.BW, None)
    grey = cv2.cvtColor(src, cv2.COLOR_RGB2GRAY) if src.ndim == 3 else src  # noqa: PLR2004
    grid = _grid(*grey.shape, dpi)
    smooth = _background(grey, dpi, grid)
    paper = _paper_level(smooth)
    if paper < PAPER_MIN_LEVEL:
        return CleanupResult(CleanupStatus.DARK, None)
    work = _Work(src, grey, smooth, grid, _layout(*grey.shape, dpi, grid))
    counts, chroma = _survey(work, cancel)
    paper_chroma = 0
    if work.colour:
        seen = int(chroma.sum())
        if seen == 0:
            return CleanupResult(CleanupStatus.NO_PAPER, None)
        paper_chroma = int(np.searchsorted(np.cumsum(chroma), (seen + 1) // 2))
        if paper_chroma > STOCK_CHROMA and output is ColourMode.COLOUR:
            return CleanupResult(CleanupStatus.STOCK, None)
    cleaned = _apply(
        work,
        output,
        tone=tone_table(policy, paper),
        protection=_protection(work, counts),
        paper_chroma=paper_chroma,
        cancel=cancel,
    )
    return CleanupResult(CleanupStatus.APPLIED, cleaned)
