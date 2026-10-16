"""Cut off what is certainly not paper: the scanner's white tail and its backing strip.

Both cuts need positive evidence and otherwise do nothing, because a missing strip of white costs
nothing and a missing line of text costs the scan:

* The tail is the run of rows at the bottom that is flat scanner white, at least a few
  millimetres long, and clearly brighter than the paper above it. A row belongs to the tail only
  if even its darker twentieth is white, so faint writing, a watermark or a footer keeps its
  rows, and only the columns that are white in the last rows are looked at (beside a narrow item
  the backing is not white). Paper that is as white as the tail, or only slightly less white,
  is not trimmed at all. A little of the tail is kept below the paper, and always the room
  around the lowest mark on the page.
* A backing strip is the scanner's own background colour, the one the photo cropper measured on
  real scans (``pipeline.crop``): a band that starts at the left or right edge of the frame, is
  almost entirely within that colour's tolerance, is at least a few millimetres wide, and lies
  next to clearly brighter paper, leaving paper that is wide enough. It is measured on the rows
  above the tail only. A printed sidebar of any other colour is not backing. Grey and 1-bit
  pages have no hue to tell it by, so they keep their sides.

The top is never trimmed.
"""

from dataclasses import dataclass, replace

import numpy as np

from fastfoto_linux.documents.loader import LoadedPage
from fastfoto_linux.documents.marks import find_marks
from fastfoto_linux.documents.modes import ColourMode
from fastfoto_linux.documents.units import mm_to_px
from fastfoto_linux.imaging import RGB_NDIM
from fastfoto_linux.pipeline.crop import BACKGROUND_PRIOR_RGB, BACKGROUND_PRIOR_TOLERANCE

# The tail below the paper.
TAIL_WHITE_MIN = 250  # a column is part of the tail when it is at least this white (0-255)
TAIL_TOLERANCE = 2  # rows within this of the tail's tone belong to it
TAIL_STEP_MIN = 4  # the paper above is at least this much darker than the tail
TAIL_PROBE_MM = 2.0  # the bottom rows that say what tone the tail is
MIN_TAIL_MM = 4.0  # a shorter tail is not worth cutting
TAIL_KEEP_MM = 3.0  # kept below the end of the paper
MARK_ROOM_MM = 5.0  # kept below the lowest mark
PAPER_PROBE_MM = 10.0  # rows of paper compared with the tail ...
PAPER_GAP_MM = 1.0  # ... starting this far above where the tail begins (the edge shadow)

# The backing beside a narrow item (its colour is the photo cropper's, imported above).
BACKING_SHARE_MIN = 0.95  # of the strip's pixels must be backing: one stripe or a word is not
BACKING_STEP = 25  # the paper beside the strip is at least this much brighter
BACKING_NEIGHBOUR_MM = 3.0
MIN_STRIP_MM = 3.0
MIN_PAPER_MM = 30.0  # never leave less paper than this
SAMPLE_COUNT = 200  # rows or columns sampled when measuring tone
ROW_TONE_PERCENTILE = 5  # a row is as bright as its darker twentieth

_PRIOR = np.asarray(BACKGROUND_PRIOR_RGB, dtype=np.float32)


@dataclass(frozen=True)
class Trimmed:
    """The page after trimming and how many pixels were removed from each side."""

    page: LoadedPage
    left: int
    right: int
    bottom: int


def _is_backing(colours: np.ndarray) -> np.ndarray:
    """For every colour (last axis RGB): is it the scanner's backing, blue-grey and within the
    tolerance of the measured background? Cream or neutral grey is never backing."""
    offset = colours.astype(np.float32) - _PRIOR
    near = np.linalg.norm(offset, axis=-1) <= BACKGROUND_PRIOR_TOLERANCE
    return near & (colours[..., 2] > colours[..., 0])


def _strip_run(band: np.ndarray, dpi: int) -> int:
    """Width in pixels of the backing strip at the left edge of ``band``; 0 when there is none.

    The strip must start at the very first column, be backing-coloured column after column and
    in nearly all of its pixels, and have clearly brighter paper beside it.
    """
    sample = band[:: max(1, band.shape[0] // SAMPLE_COUNT)]
    columns = np.median(sample, axis=0)  # one colour per column
    backing = _is_backing(columns)
    run = len(columns) if backing.all() else int(backing.argmin())
    if run < mm_to_px(MIN_STRIP_MM, dpi):
        return 0
    if _is_backing(sample[:, :run]).mean() < BACKING_SHARE_MIN:
        return 0
    beside = columns[run : run + mm_to_px(BACKING_NEIGHBOUR_MM, dpi)]
    if beside.size == 0 or beside.mean() < columns[:run].mean() + BACKING_STEP:
        return 0
    return run


def _side_cuts(band: np.ndarray, dpi: int) -> tuple[int, int]:
    """Pixels to cut from the left and the right; (0, 0) unless both are believable."""
    left, right = _strip_run(band, dpi), _strip_run(band[:, ::-1], dpi)
    if band.shape[1] - left - right < mm_to_px(MIN_PAPER_MM, dpi):
        return 0, 0
    return left, right


def _tail_columns(pixels: np.ndarray, dpi: int) -> np.ndarray:
    """Indices of the columns that are scanner-white in the last rows: where the tail is.

    Beside a narrow item the backing runs down the whole frame and is not white.
    """
    probe = pixels[-mm_to_px(TAIL_PROBE_MM, dpi) :]
    grey = probe.mean(axis=2) if probe.ndim == RGB_NDIM else probe
    return np.flatnonzero(np.median(grey, axis=0) >= TAIL_WHITE_MIN)


def _row_tones(pixels: np.ndarray, columns: np.ndarray) -> np.ndarray:
    """The brightness of every row over a sample of ``columns``: its darker twentieth, so that
    writing which covers only part of a row, however faint, still darkens it."""
    picked = columns[:: max(1, columns.size // SAMPLE_COUNT)]
    sample = pixels[:, picked].astype(np.float32)
    grey = sample.mean(axis=2) if sample.ndim == RGB_NDIM else sample
    return np.percentile(grey, ROW_TONE_PERCENTILE, axis=1)


def _tail_start(pixels: np.ndarray, dpi: int) -> int | None:
    """First row of the scanner's white tail, or None unless it is certain."""
    columns = _tail_columns(pixels, dpi)
    if columns.size < mm_to_px(MIN_PAPER_MM, dpi):
        return None
    rows = _row_tones(pixels, columns)
    level = float(np.median(rows[-mm_to_px(TAIL_PROBE_MM, dpi) :]))
    not_tail = np.flatnonzero(rows < level - TAIL_TOLERANCE)
    start = int(not_tail[-1]) + 1 if not_tail.size else 0
    if len(rows) - start < mm_to_px(MIN_TAIL_MM, dpi):
        return None
    paper_end = max(0, start - mm_to_px(PAPER_GAP_MM, dpi))
    paper = rows[max(0, paper_end - mm_to_px(PAPER_PROBE_MM, dpi)) : paper_end]
    if paper.size == 0 or level - float(np.median(paper)) < TAIL_STEP_MIN:
        return None
    return start


def _bottom_cut(page: LoadedPage) -> int:
    """Rows to cut from the bottom of ``page``."""
    height = page.pixels.shape[0]
    start = _tail_start(page.pixels, page.dpi)
    if start is None:
        return 0
    keep = start + mm_to_px(TAIL_KEEP_MM, page.dpi)
    marks = find_marks(page)
    if marks:
        keep = max(keep, max(mark.y1 for mark in marks) + mm_to_px(MARK_ROOM_MM, page.dpi))
    return max(0, height - keep)


def trim_page(page: LoadedPage) -> Trimmed:
    """Trim the tail below the paper and backing strips beside it; when unsure, trim nothing.

    The input is not modified; the trimmed page may share memory with it.
    """
    if page.kind is ColourMode.BW:
        return Trimmed(page, 0, 0, 0)
    left = right = 0
    if page.kind is ColourMode.COLOUR:
        tail = _tail_start(page.pixels, page.dpi)  # the strip is measured above the tail
        left, right = _side_cuts(page.pixels if tail is None else page.pixels[:tail], page.dpi)
    sides = replace(page, pixels=page.pixels[:, left : page.pixels.shape[1] - right])
    bottom = _bottom_cut(sides)
    kept = sides.pixels[: sides.pixels.shape[0] - bottom]
    return Trimmed(replace(page, pixels=kept), left, right, bottom)
