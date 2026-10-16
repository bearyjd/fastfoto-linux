"""Cut off what is certainly empty: the scanner's blank white tail and its backing strip.

Both cuts need positive evidence and otherwise do nothing, because a missing strip of white costs
nothing and a missing line of text costs the scan:

* The tail is the run of rows at the bottom that is flat scanner white (columns at least 250 of
  255 in the last rows; beside a narrow item the backing is not white), at least 4 mm long and at
  least 4 levels brighter than the 10 mm of rows directly above it. A row is as bright as its
  darker twentieth, so writing across a twentieth of its width keeps it. Where those 10 mm are as
  white as the tail, or less than 4 levels darker, nothing is trimmed. Below solid content the
  empty paper counts as tail when it is that close to the tail's white, so it is trimmed with it.
  Of the tail 3 mm are kept, and always 5 mm below the lowest mark or the lowest ink: ink is any
  cluster that is 12 or more levels darker than the tail's white and whose longer side is 0.3 mm
  or more, in whole pixels rounded up and at least 2 (a lone page number, a faint footer), found
  in every tail column whatever the row tones say. Only ink fainter than that, which cannot be
  told from paper texture, can be trimmed away.
* A backing strip is the scanner's own background colour, the one the photo cropper measured on
  real scans (``pipeline.crop``): RGB distance of at most 20 from (202, 210, 219), blue above
  red. It is a band of columns that starts at the left or right edge of the frame, in each of
  which at least 99% of the rows are backing (so a tilted receipt is cut only up to its
  nearest corner, and a tab of paper that sticks out stops the cut), at least 3 mm wide, next to
  paper that is 25 levels brighter, leaving at least 30 mm of paper. It is measured on the rows
  above the tail only. A printed sidebar of any other colour is not backing; one printed
  edge to edge and full height within that distance is, and is cut. Grey and 1-bit pages have no
  hue to tell it by, so they keep their sides.

The last check applies to every strip a trim would remove, the tail and each side strip, over
all of its columns and rows: the tail is judged in the columns that are white, but the cut spans
them all, so a pale slip or a sticky note that hangs below the paper would go with it. A cut is
cancelled, and its strip kept, when the strip holds a cluster of ink size that is neither blank
white nor backing. Blank white is less than 12 levels darker than the tail's white. Backing is an
area of backing colour that is joined to a side of the strip (on a grey page, a grey within the
same distance of the backing's grey, since there is no hue); pixels where backing and white blend,
at the edge of a blurred scan, are no content either. What is cut is therefore what is certainly
empty, blank white or the scanner's backing, with the limits of that test: a note of the backing's
colour that touches the side of its strip cannot be told from backing, and a stroke under 3
pixels wide within 2 pixels of both white and backing is taken for the blur of an edge. A page
that would be under 10 mm tall or wide after trimming (the least ``find_marks`` accepts) is kept
whole.

The top is never trimmed.
"""

import logging
import math
from dataclasses import dataclass, replace

import cv2
import numpy as np

from fastfoto_linux.documents.loader import MIN_PAGE_MM, WHITE, LoadedPage
from fastfoto_linux.documents.marks import find_marks
from fastfoto_linux.documents.modes import ColourMode
from fastfoto_linux.documents.units import MM_PER_INCH, mm_to_px
from fastfoto_linux.imaging import RGB_NDIM
from fastfoto_linux.pipeline.crop import BACKGROUND_PRIOR_RGB, BACKGROUND_PRIOR_TOLERANCE

# The tail below the paper.
TAIL_WHITE_MIN = 250  # a column is part of the tail when it is at least this white (0-255)
TAIL_TOLERANCE = 2  # rows within this of the tail's tone belong to it
TAIL_STEP_MIN = 4  # the paper above is at least this much darker than the tail
TAIL_PROBE_MM = 2.0  # the bottom rows that say what tone the tail is
MIN_TAIL_MM = 4.0  # a shorter tail is not worth cutting
TAIL_KEEP_MM = 3.0  # kept below the end of the paper
MARK_ROOM_MM = 5.0  # kept below the lowest mark or ink
INK_DEVIATION = 12  # levels darker than the tail's white: 4x its noise, far under any pencil
INK_CLUSTER_MM = 0.3  # the longer side of a cluster that counts (dust is smaller)
INK_CLUSTER_MIN_PX = 2  # one pixel is noise at any resolution; 0.3 mm is rounded up to pixels
PAPER_PROBE_MM = 10.0  # rows of paper compared with the tail ...
PAPER_GAP_MM = 1.0  # ... starting this far above where the tail begins (the edge shadow)

# The backing beside a narrow item (its colour is the photo cropper's, imported above).
COLUMN_BACKING_SHARE = 0.99  # a column is cut only when this share of its rows is backing
STRIP_ROWS = 1000  # rows sampled when measuring a column, so that 1% is ten rows
BACKING_STEP = 25  # the paper beside the strip is at least this much brighter
BACKING_NEIGHBOUR_MM = 3.0
MIN_STRIP_MM = 3.0
MIN_PAPER_MM = 30.0  # never leave less paper than this
SAMPLE_COUNT = 200  # rows or columns sampled when measuring tone
ROW_TONE_PERCENTILE = 5  # a row is as bright as its darker twentieth

# The last check on every strip that is cut.
FRINGE_PX = 2  # where backing and white blend, a pixel lies this close to both

_PRIOR = np.asarray(BACKGROUND_PRIOR_RGB, dtype=np.float32)
# The backing as a grey page holds it (a grey page has no hue to tell backing by).
_PRIOR_GREY = int(
    cv2.cvtColor(np.round(_PRIOR).astype(np.uint8).reshape(1, 1, 3), cv2.COLOR_RGB2GRAY)[0, 0]
)
logger = logging.getLogger(__name__)


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


def _paper_beside(colours: np.ndarray, backing: np.ndarray, run: int, dpi: int) -> bool:
    """Is what lies beside the strip (``run`` columns wide) paper clearly brighter than it?

    Judged on the beside pixels that are not backing, so the edge of a tilted receipt, where
    most of them still are, does not hide the paper.
    """
    near = slice(run, run + mm_to_px(BACKING_NEIGHBOUR_MM, dpi))
    paper = colours[:, near][~backing[:, near]]  # not empty: column ``run`` is not all backing
    return float(np.median(paper.mean(axis=1))) >= colours[:, :run].mean() + BACKING_STEP


def _strip_run(band: np.ndarray, dpi: int) -> int:
    """Width in pixels of the backing strip at the left edge of ``band``; 0 when there is none.

    The strip is the columns, from the very first, in which at least ``COLUMN_BACKING_SHARE``
    of the rows are backing-coloured; the first column that is not ends it. It must be a few
    millimetres wide, leave paper, and have clearly brighter paper beside it.
    """
    limit = band.shape[1] - mm_to_px(MIN_PAPER_MM, dpi)
    if limit < mm_to_px(MIN_STRIP_MM, dpi):
        return 0
    rows = band[:: max(1, band.shape[0] // STRIP_ROWS)]
    colours = rows[:, : limit + mm_to_px(BACKING_NEIGHBOUR_MM, dpi)]
    backing = _is_backing(colours)
    whole = backing.mean(axis=0) >= COLUMN_BACKING_SHARE
    run = len(whole) if whole.all() else int(whole.argmin())
    if not mm_to_px(MIN_STRIP_MM, dpi) <= run <= limit:
        return 0
    return run if _paper_beside(colours, backing, run, dpi) else 0


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


def _grey_of(pixels: np.ndarray) -> np.ndarray:
    """The darkest channel of every pixel (the page itself when it is grey)."""
    return pixels.min(axis=2) if pixels.ndim == RGB_NDIM else pixels


def _tail_white(pixels: np.ndarray, dpi: int) -> float:
    """The scanner's white: the median darkest channel of the last rows in the tail columns,
    or pure white where no column is white."""
    columns = _tail_columns(pixels, dpi)
    if columns.size == 0:
        return float(WHITE)
    probe = _grey_of(pixels[-mm_to_px(TAIL_PROBE_MM, dpi) :])[:, columns]
    return float(np.median(probe))


def _ink_size_px(dpi: int) -> int:
    """Pixels in the longer side of the smallest ink cluster: ``INK_CLUSTER_MM`` rounded up, so
    that nothing shorter than that counts (at 200 dpi 0.3 mm is 3 pixels, not 2)."""
    return max(INK_CLUSTER_MIN_PX, math.ceil(INK_CLUSTER_MM * dpi / MM_PER_INCH))


def _ink_clusters(mask: np.ndarray, dpi: int) -> np.ndarray:
    """The boxes (OpenCV statistics rows) of the clusters of ``mask`` that are ink-sized."""
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    boxes = stats[1:count]  # row 0 is the background
    longest = np.maximum(boxes[:, cv2.CC_STAT_WIDTH], boxes[:, cv2.CC_STAT_HEIGHT])
    return boxes[longest >= _ink_size_px(dpi)]


def _lowest_ink(page: LoadedPage, start: int) -> int | None:
    """The row just below the lowest ink in the would-be tail ``pixels[start:]``; None if none.

    Ink is a cluster of ``INK_CLUSTER_MM`` or more whose darkest channel is ``INK_DEVIATION``
    levels below the tail's white, in any of the tail columns. Unlike a mark it needs no
    contrast with the paper, and unlike a row's tone it sees one short word.
    """
    grey = _grey_of(page.pixels[start:])[:, _tail_columns(page.pixels, page.dpi)]
    white = _tail_white(page.pixels, page.dpi)
    boxes = _ink_clusters(grey <= white - INK_DEVIATION, page.dpi)
    if not boxes.size:
        return None
    return start + int((boxes[:, cv2.CC_STAT_TOP] + boxes[:, cv2.CC_STAT_HEIGHT]).max())


def _backing_tone(strip: np.ndarray) -> np.ndarray:
    """Which pixels have the backing's colour (on a grey page, its grey, as far from it)."""
    if strip.ndim == RGB_NDIM:
        return _is_backing(strip)
    return np.abs(strip.astype(np.int16) - _PRIOR_GREY) <= BACKGROUND_PRIOR_TOLERANCE


def _joined_to_sides(tone: np.ndarray) -> np.ndarray:
    """The part of ``tone`` that is connected to the left or the right edge of the array: the
    backing runs in from the side of the frame, a note lying in the strip does not."""
    count, labels = cv2.connectedComponents(tone.astype(np.uint8), connectivity=8)
    joined = np.zeros(count, dtype=bool)
    joined[labels[:, 0]] = True
    joined[labels[:, -1]] = True
    joined[0] = False  # label 0 is what is not ``tone``
    return joined[labels]


def _blended(white: np.ndarray, backing: np.ndarray) -> np.ndarray:
    """Pixels within ``FRINGE_PX`` of both white and backing: where a blurred edge between the
    two is neither, and where a slip or a stroke, which borders only one of them, is not."""
    kernel = np.ones((2 * FRINGE_PX + 1, 2 * FRINGE_PX + 1), np.uint8)
    near_white = cv2.dilate(white.astype(np.uint8), kernel).astype(bool)
    near_backing = cv2.dilate(backing.astype(np.uint8), kernel).astype(bool)
    return near_white & near_backing


def _holds_content(strip: np.ndarray, white: float, dpi: int) -> bool:
    """Does ``strip``, which a trim would remove, hold an ink-sized cluster that is neither
    blank white (less than ``INK_DEVIATION`` darker than ``white``) nor backing?"""
    marked = _grey_of(strip) <= white - INK_DEVIATION
    if not marked.any():
        return False
    backing = _joined_to_sides(_backing_tone(strip))
    unexplained = marked & ~backing & ~_blended(~marked, backing)
    return bool(_ink_clusters(unexplained, dpi).size)


def _vetted_sides(page: LoadedPage, left: int, right: int) -> tuple[int, int]:
    """The side cuts, each cancelled when its strip (every row, tail rows too) holds content."""
    width = page.pixels.shape[1]
    white = _tail_white(page.pixels, page.dpi)
    if left and _holds_content(page.pixels[:, :left], white, page.dpi):
        left = 0
    if right and _holds_content(page.pixels[:, width - right :], white, page.dpi):
        right = 0
    return left, right


def _bottom_cut(page: LoadedPage) -> int:
    """Rows to cut from the bottom of ``page``."""
    height = page.pixels.shape[0]
    start = _tail_start(page.pixels, page.dpi)
    if start is None:
        return 0
    ink = _lowest_ink(page, start)
    reach = [mark.y1 for mark in find_marks(page)] + ([] if ink is None else [ink])
    room = mm_to_px(MARK_ROOM_MM, page.dpi)
    keep = max([start + mm_to_px(TAIL_KEEP_MM, page.dpi), *(row + room for row in reach)])
    cut = max(0, height - keep)
    if cut and _holds_content(
        page.pixels[height - cut :], _tail_white(page.pixels, page.dpi), page.dpi
    ):
        return 0
    return cut


def _trimmed(page: LoadedPage) -> Trimmed:
    left = right = 0
    if page.kind is ColourMode.COLOUR:
        tail = _tail_start(page.pixels, page.dpi)  # the strip is measured above the tail
        left, right = _side_cuts(page.pixels if tail is None else page.pixels[:tail], page.dpi)
        left, right = _vetted_sides(page, left, right)
    sides = replace(page, pixels=page.pixels[:, left : page.pixels.shape[1] - right])
    bottom = _bottom_cut(sides)
    kept = sides.pixels[: sides.pixels.shape[0] - bottom]
    return Trimmed(replace(page, pixels=kept), left, right, bottom)


def trim_page(page: LoadedPage) -> Trimmed:
    """Trim the tail below the paper and backing strips beside it; when unsure, trim nothing.

    The input is not modified; the trimmed page may share memory with it. A page that would be
    left under ``MIN_PAGE_MM`` each way is returned whole.
    """
    if page.kind is ColourMode.BW:
        return Trimmed(page, 0, 0, 0)
    result = _trimmed(page)
    if min(result.page.pixels.shape[:2]) < mm_to_px(MIN_PAGE_MM, page.dpi):
        logger.debug("trimming would leave under %.0f mm of the page; kept whole", MIN_PAGE_MM)
        return Trimmed(page, 0, 0, 0)
    return result
