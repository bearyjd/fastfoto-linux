"""Cut off what is certainly not paper: the scanner's white tail and a blue-grey backing strip.

Both cuts need positive evidence and otherwise do nothing, because a missing strip of white costs
nothing and a missing line of text costs the scan:

* The tail is the run of rows at the bottom that is flat scanner white, at least a few
  millimetres long, and clearly brighter than the paper above it. Paper that is as white as the
  tail, or only slightly less white, is not trimmed at all. A little of the tail is kept below the
  paper, and always the room around the lowest mark on the page.
* A backing strip is a uniform, blue-grey, full-height band along the left or right edge, at least
  a few millimetres wide, next to clearly brighter paper, leaving paper that is wide enough.
  Grey and 1-bit pages have no hue to tell it by, so they keep their sides.

The top is never trimmed.
"""

from dataclasses import dataclass, replace

import numpy as np

from fastfoto_linux.documents.loader import LoadedPage
from fastfoto_linux.documents.marks import find_marks
from fastfoto_linux.documents.modes import ColourMode
from fastfoto_linux.documents.units import mm_to_px
from fastfoto_linux.imaging import RGB_NDIM

# The tail below the paper.
TAIL_WHITE_MIN = 250  # the tail is at least this white (0-255)
TAIL_TOLERANCE = 2  # rows within this of the tail's tone belong to it
TAIL_STEP_MIN = 4  # the paper above is at least this much darker than the tail
TAIL_PROBE_MM = 2.0  # the bottom rows that say what tone the tail is
MIN_TAIL_MM = 4.0  # a shorter tail is not worth cutting
TAIL_KEEP_MM = 3.0  # kept below the end of the paper
MARK_ROOM_MM = 5.0  # kept below the lowest mark
PAPER_PROBE_MM = 10.0  # rows of paper compared with the tail ...
PAPER_GAP_MM = 1.0  # ... starting this far above where the tail begins (the edge shadow)

# The backing beside a narrow item.
BACKING_PROBE_MM = 1.0  # the edge columns that say what colour the backing is
BACKING_BLUE_MIN = 12  # blue exceeds red by at least this
BACKING_SPREAD_MAX = 70  # and the channels are no further apart than this
BACKING_TONE = (70, 225)  # mean level: not black, not paper-white
BACKING_TOLERANCE = 14  # columns within this of the backing colour belong to it
BACKING_STD_MAX = 14  # grey levels of variation allowed inside the strip
BACKING_STEP = 25  # the paper beside the strip is at least this much brighter
BACKING_NEIGHBOUR_MM = 3.0
MIN_STRIP_MM = 3.0
MIN_PAPER_MM = 30.0  # never leave less paper than this
SAMPLE_COUNT = 200  # rows or columns sampled when measuring tone
ROW_TONE_PERCENTILE = 75  # the row is as bright as its brighter three quarters


@dataclass(frozen=True)
class Trimmed:
    """The page after trimming and how many pixels were removed from each side."""

    page: LoadedPage
    left: int
    right: int
    bottom: int


def _is_backing_colour(colour: np.ndarray) -> bool:
    blue_over_red = colour[2] - colour[0]
    spread = colour.max() - colour.min()
    return bool(
        blue_over_red >= BACKING_BLUE_MIN
        and spread <= BACKING_SPREAD_MAX
        and BACKING_TONE[0] <= colour.mean() <= BACKING_TONE[1]
    )


def _strip_run(rgb: np.ndarray, dpi: int) -> int:
    """Width in pixels of the backing strip at the left edge of ``rgb``; 0 when there is none."""
    sample = rgb[:: max(1, rgb.shape[0] // SAMPLE_COUNT)]
    columns = np.median(sample, axis=0)  # one colour per column
    colour = columns[: mm_to_px(BACKING_PROBE_MM, dpi)].mean(axis=0)
    if not _is_backing_colour(colour):
        return 0
    differs = np.abs(columns - colour).max(axis=1) > BACKING_TOLERANCE
    run = int(differs.argmax()) if differs.any() else len(columns)
    if run < mm_to_px(MIN_STRIP_MM, dpi):
        return 0
    if sample[:, :run].reshape(-1, 3).std(axis=0).max() > BACKING_STD_MAX:
        return 0
    beside = columns[run : run + mm_to_px(BACKING_NEIGHBOUR_MM, dpi)]
    if beside.size == 0 or beside.mean() < colour.mean() + BACKING_STEP:
        return 0
    return run


def _side_cuts(rgb: np.ndarray, dpi: int) -> tuple[int, int]:
    """Pixels to cut from the left and the right; (0, 0) unless both are believable."""
    left, right = _strip_run(rgb, dpi), _strip_run(rgb[:, ::-1], dpi)
    if rgb.shape[1] - left - right < mm_to_px(MIN_PAPER_MM, dpi):
        return 0, 0
    return left, right


def _row_tones(pixels: np.ndarray) -> np.ndarray:
    """The brightness of every row, from a sample of its columns.

    A high percentile rather than the median: on a grey page the backing beside a narrow item
    cannot be told by its colour, and would otherwise make every row look darker than the paper
    and the tail.
    """
    sample = pixels[:, :: max(1, pixels.shape[1] // SAMPLE_COUNT)].astype(np.float32)
    grey = sample.mean(axis=2) if sample.ndim == RGB_NDIM else sample
    return np.percentile(grey, ROW_TONE_PERCENTILE, axis=1)


def _tail_start(rows: np.ndarray, dpi: int) -> int | None:
    """First row of the scanner's white tail, or None unless it is certain."""
    level = float(np.median(rows[-mm_to_px(TAIL_PROBE_MM, dpi) :]))
    if level < TAIL_WHITE_MIN:
        return None
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
    start = _tail_start(_row_tones(page.pixels), page.dpi)
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
    left, right = _side_cuts(page.pixels, page.dpi) if page.kind is ColourMode.COLOUR else (0, 0)
    sides = replace(page, pixels=page.pixels[:, left : page.pixels.shape[1] - right])
    bottom = _bottom_cut(sides)
    kept = sides.pixels[: sides.pixels.shape[0] - bottom]
    return Trimmed(replace(page, pixels=kept), left, right, bottom)
