"""Cut off what is certainly empty: the scanner's blank white tail and its backing.

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
  hue to tell it by, so they keep their sides: a grey page is trimmed at the bottom only, never at
  a side, and a 1-bit page not at all. In grey the backing is also the tone of pastel paper and of
  a pale slip, so a grey page loses the white tail only, never a side, and a grey receipt keeps
  its tail (a missed trim, by design: ``ffscan doc scan`` will scan in colour and make the grey
  page after trimming, and a colour page is trimmed in colour before it is made grey or 1-bit).

The last check applies to every strip a trim would remove, the tail and each side strip, over all of
its columns and rows, on a blurred copy (3x3) so that scanner noise makes no clusters of its own,
and a dark dot grows by 2 pixels into a cluster (two or three pixels at 300 dpi). The tail is judged
in the columns that are white, but the cut spans them all, so a pale slip or a sticky note that
hangs below the paper would go with it. A cut is cancelled, and its strip kept, when the strip holds
a cluster of ink size that is neither blank white nor backing. Blank white is less than 12 levels
darker than the tail's white. On a colour page backing is an area of backing colour that is joined
to a side of the strip. On a grey page nothing but the tone tells backing, and a pale slip or
pastel paper has it wherever it lies, so a grey page has no backing: only blank white is exempt,
and a cluster of backing grey keeps the strip. Where the backing beside a receipt runs on below the
paper, the strip holds backing grey, so the tail there is kept. On a colour page, pixels where
backing and white blend, at the edge of a blurred scan, are no content either. The strip of a
band cut is judged with the scanner's pad exempt pixel by pixel (white, and the pixels within 2
pixels of both white and backing; see ``band``), its backing joined to a side of the strip or to
its first row, the band, by backing alone: the pad joins nothing. The strict tolerance above
applies there too, except to the shadow's specks and dust (see ``guard``), and ink in the white
tail is found as the tail rule finds it. What is cut is therefore what is certainly empty, blank
white or the scanner's backing, with the limits of that test: on a colour page a note of the
backing's colour that touches the side of its strip, or the band, cannot be told from backing (in
a band cut's strip that includes a scrap at a side in the first 3 mm of the tail, which goes with
the band), a stroke under 3 pixels wide within 2 pixels of both white and backing is taken for the
blur of an edge, and a stroke 1 pixel wide is diluted to a third of its depth by the blur (on a
slip only 5 levels below the tail's white it must be about 21 levels darker than the slip to
count).
A page that would be under 10 mm tall or wide after trimming (the least ``find_marks``
accepts) is kept whole.

The top is trimmed only by the band rule of ``band``: the scanner's full-width backing band at the
bottom (found above the white tail, and cut with the pad and the tail below it) and at the top is
cut, below the edge line and with at least 1 mm of it left at the bottom, on colour pages only. At
least 30 mm of page stay after each cut and the last check applies to the whole strip, the first
3 mm of the tail included (the ink search of the tail rule looks at the rest); the white-tail rule
runs where there is no band cut. After a band cut the new edge is the paper's, so
``Trimmed.tail_rows`` is 0 and the blank-page margin is whole.
"""

import logging
from dataclasses import dataclass, replace

import cv2
import numpy as np

from fastfoto_linux.documents.band import BOTTOM_EDGE, TOP_EDGE, EdgeRule, backing_mask, band_cut
from fastfoto_linux.documents.guard import INK_DEVIATION, grey_of, holds_content, ink_clusters
from fastfoto_linux.documents.loader import MIN_PAGE_MM, WHITE, LoadedPage
from fastfoto_linux.documents.marks import find_marks
from fastfoto_linux.documents.modes import ColourMode
from fastfoto_linux.documents.units import mm_to_px
from fastfoto_linux.imaging import RGB_NDIM

# The tail below the paper.
TAIL_WHITE_MIN = 250  # a column is part of the tail when it is at least this white (0-255)
TAIL_TOLERANCE = 2  # rows within this of the tail's tone belong to it
TAIL_STEP_MIN = 4  # the paper above is at least this much darker than the tail
TAIL_PROBE_MM = 2.0  # the bottom rows that say what tone the tail is
MIN_TAIL_MM = 4.0  # a shorter tail is not worth cutting
TAIL_KEEP_MM = 3.0  # kept below the end of the paper
MARK_ROOM_MM = 5.0  # kept below the lowest mark or ink
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

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Trimmed:
    """The page after trimming and how many pixels were removed from each side."""

    page: LoadedPage
    left: int
    right: int
    bottom: int
    top: int = 0
    band_bottom: bool = False  # the bottom cut ended at the paper's edge, in the backing band

    @property
    def tail_rows(self) -> int:
        """Rows cut off the bottom that were the white tail: they take their share of the
        blank-page margin with them. A band cut leaves the paper's own edge, so none do."""
        return 0 if self.band_bottom else self.bottom


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
    backing = backing_mask(colours)
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


def _tail_white(pixels: np.ndarray, dpi: int) -> float:
    """The scanner's white: the median darkest channel of the last rows in the tail columns,
    or pure white where no column is white."""
    columns = _tail_columns(pixels, dpi)
    if columns.size == 0:
        return float(WHITE)
    probe = grey_of(pixels[-mm_to_px(TAIL_PROBE_MM, dpi) :])[:, columns]
    return float(np.median(probe))


def _lowest_ink(page: LoadedPage, start: int) -> int | None:
    """The row just below the lowest ink in the would-be tail ``pixels[start:]``; None if none.

    Ink is a cluster of ``INK_CLUSTER_MM`` or more whose darkest channel is ``INK_DEVIATION``
    levels below the tail's white, in any of the tail columns. Unlike a mark it needs no
    contrast with the paper, and unlike a row's tone it sees one short word.
    """
    grey = grey_of(page.pixels[start:])[:, _tail_columns(page.pixels, page.dpi)]
    white = _tail_white(page.pixels, page.dpi)
    boxes = ink_clusters(grey <= white - INK_DEVIATION, page.dpi)
    if not boxes.size:
        return None
    return start + int((boxes[:, cv2.CC_STAT_TOP] + boxes[:, cv2.CC_STAT_HEIGHT]).max())


def _vetted_sides(page: LoadedPage, left: int, right: int) -> tuple[int, int]:
    """The side cuts, each cancelled when its strip (every row, tail rows too) holds content."""
    width = page.pixels.shape[1]
    white = _tail_white(page.pixels, page.dpi)
    if left and holds_content(page.pixels[:, :left], white, page.dpi):
        left = 0
    if right and holds_content(page.pixels[:, width - right :], white, page.dpi):
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
    if cut and holds_content(
        page.pixels[height - cut :], _tail_white(page.pixels, page.dpi), page.dpi
    ):
        return 0
    return cut


def _band_cut(page: LoadedPage, rule: EdgeRule, other: int = 0) -> int:
    """Rows to cut at the edge ``rule`` is for when the scanner's backing band lies there (at the
    bottom with the white tail below it); 0 when there is none or the cut is not safe, which
    leaves the tail rule to decide.

    The band is looked for above the white tail. Not safe: ``other`` rows are cut at the opposite
    edge and 30 mm of page must stay; the last check finds something but pad (white, and where it
    blends with the backing) and backing in the band, the slanted pad under it and the first
    ``TAIL_KEEP_MM`` of the tail, where the pad's edge rings; or the ink search of the tail rule
    finds ink in the rest of the white tail, which goes with the band.
    """
    if page.kind is not ColourMode.COLOUR:
        return 0
    height = page.pixels.shape[0]
    tail = _tail_start(page.pixels, page.dpi) if rule.bottom else None
    body = height if tail is None else tail
    cut = band_cut(page.pixels[:body], page.dpi, rule)
    if cut is None or body - cut - other < mm_to_px(MIN_PAPER_MM, page.dpi):
        return 0
    below = body if tail is None else body + mm_to_px(TAIL_KEEP_MM, page.dpi)
    strip = page.pixels[body - cut : below] if rule.bottom else page.pixels[:cut][::-1]
    white = _tail_white(page.pixels, page.dpi)
    if holds_content(strip, white, page.dpi, pad=True):
        return 0
    return 0 if tail is not None and _lowest_ink(page, below) is not None else height - body + cut


def _trimmed(page: LoadedPage) -> Trimmed:
    left = right = 0
    if page.kind is ColourMode.COLOUR:
        tail = _tail_start(page.pixels, page.dpi)  # the strip is measured above the tail
        left, right = _side_cuts(page.pixels if tail is None else page.pixels[:tail], page.dpi)
        left, right = _vetted_sides(page, left, right)
    sides = replace(page, pixels=page.pixels[:, left : page.pixels.shape[1] - right])
    band = _band_cut(sides, BOTTOM_EDGE)
    bottom = band or _bottom_cut(sides)
    top = _band_cut(sides, TOP_EDGE, other=bottom)
    kept = sides.pixels[top : sides.pixels.shape[0] - bottom]
    return Trimmed(replace(page, pixels=kept), left, right, bottom, top, bool(band))


def trim_page(page: LoadedPage) -> Trimmed:
    """Trim the tail below the paper, the backing band and strips beside it; when unsure, trim
    nothing.

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
