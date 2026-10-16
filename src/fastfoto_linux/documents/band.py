"""The scanner's backing band below and above the paper: where the paper ends on real pages.

From the bottom edge of a deskewed page upward the scanner delivers a slanted pad of pure white
(the area outside the scanned region; a row passes from nearly all pad to none within about 10
mm), then a full-width backing band of 6 to 15 mm in the backing colour of ``pipeline.crop``,
darker next to the paper (a shadow, up to 36 from the backing colour), then an optional edge line
of about 1 mm (24 to 64% of its pixels are dark), then the paper, which is often pure 255 like the
pad and so cannot be told from it by its brightness. At the top there are 1 to 2 mm of the same
backing (the first row partly pad), the edge line, the paper. The full-width backing band is the
reliable sign of where the paper ends.

* A band row is one in which at least 95% of all the pixels, the whole width, are backing or its
  shadow. It is measured over the whole width, never over what is not white: a narrow receipt on
  the backing, or a row of blank white paper, is not a band row.
* The band is a run of band rows that starts within 20 mm of the bottom edge (the pad and its
  slant) or within 0.5 mm of the top edge, with nothing but pad and backing between the run and
  the edge. It is a band of 3 to 20 mm at the bottom and of 1 to 4 mm at the top; a longer run (a
  backing-coloured header or form margin) is not a band and nothing is cut.
* The cut is made at the band's border with the paper, never through the edge line: the edge line
  is not backing, so it ends the run and is kept whole. At the bottom at most 1 mm of the band
  stays, at the top none. The shadow is darker than what the last check in ``trim`` calls backing
  (at most 20 from the backing colour), so the cut never takes a row of the last 4 mm of the band
  in which that is not backing in 95% of the pixels: a darker shadow stays with the paper.
* At least 30 mm of page stay after each cut, and the last check in ``trim`` applies to each
  cut, except to the rows the pad's slant still reaches, counted from the frame's edge up to the
  first row with no pad in it: it tapers to slivers under 3 px that the blur of the check turns
  into tones that are neither white nor backing. White further in is not pad. Those rows are
  judged here instead: 99% of every row between the edge and the band is pad or backing (the
  blend of the two, under 2 px from both, included).
* After a band cut the new edge is the paper's, so the blank-page margin is measured in full
  from the new edge (``Trimmed.tail_rows``): the kept edge line is margin, not a mark.

Only colour pages are looked at: grey and 1-bit pages are not cut by the band rule (a grey page
has no hue to tell the backing by). Limits: side slivers of up to 2 mm are left, because they are
slanted and the strip rule needs 3 mm; a full-width bar in the backing colour at the top or bottom
edge is cut with the band, as a full-height sidebar of that colour is at a side.
"""

from dataclasses import dataclass

import cv2
import numpy as np

from fastfoto_linux.documents.units import mm_to_px
from fastfoto_linux.pipeline.crop import BACKGROUND_PRIOR_RGB, BACKGROUND_PRIOR_TOLERANCE

BAND_SHARE = 0.95  # a band row is at least this share backing, across the whole width
SHADOW_TOLERANCE = 36  # a shadow pixel is at most this far from the backing colour (RGB)
PAD_WHITE_MIN = 250  # the pad is pure 255; every channel at least this counts as white
PAD_EMPTY_SHARE = 0.99  # the rows between the edge and the band are pad and backing to this share
FRINGE_PX = 2  # where the pad and the backing blend, a pixel lies this close to both
PAD_ROW_SHARE = 0.001  # a row with this share of pad pixels is still in the pad's slant
PAD_MARGIN_PX = 3  # rows beyond the pad that the blur of the last check still takes it from
SHADOW_ZONE_MM = 4.0  # the shadow lies in this much of the band next to the paper
WINDOW_SLACK_MM = 1.0  # rows looked at beyond the longest band (the paper, to see its end)

_PRIOR = np.asarray(BACKGROUND_PRIOR_RGB, dtype=np.float32)


@dataclass(frozen=True)
class EdgeRule:
    """Where to look for a band and how big it may be (all in millimetres)."""

    bottom: bool
    reach_mm: float  # the band starts at most this far from the edge of the frame
    min_mm: float
    max_mm: float
    keep_mm: float  # of the band stays next to the paper


@dataclass(frozen=True)
class Band:
    """A band found at an edge, in rows counted from the edge of the frame."""

    cut: int  # rows to remove: the pad, the band, and its shadow up to what the rule keeps
    pad: int  # of those, the rows still touched by the pad's slant: the last check skips them


BOTTOM_EDGE = EdgeRule(bottom=True, reach_mm=20.0, min_mm=3.0, max_mm=20.0, keep_mm=1.0)
# the first row at the top is partly pad, not a band row: a band of 1 mm is a run a little shorter
TOP_EDGE = EdgeRule(bottom=False, reach_mm=0.5, min_mm=0.75, max_mm=4.0, keep_mm=0.0)


def backing_mask(colours: np.ndarray, tolerance: float = BACKGROUND_PRIOR_TOLERANCE) -> np.ndarray:
    """For every colour (last axis RGB): is it the scanner's backing, blue-grey and within
    ``tolerance`` of the measured background? Cream or neutral grey is never backing."""
    offset = colours.astype(np.float32) - _PRIOR
    near = np.linalg.norm(offset, axis=-1) <= tolerance
    return near & (colours[..., 2] > colours[..., 0])


def _edge_first(pixels: np.ndarray, rule: EdgeRule, dpi: int) -> np.ndarray:
    """The rows of ``pixels`` next to the edge the rule is for, the row on the edge first."""
    rows = mm_to_px(rule.reach_mm + rule.max_mm + WINDOW_SLACK_MM, dpi)
    return pixels[::-1][:rows] if rule.bottom else pixels[:rows]


def _empty_rows(loose: np.ndarray, white: np.ndarray) -> np.ndarray:
    """Which rows are pad and backing to ``PAD_EMPTY_SHARE``, the pixels where the two blend
    (the anti-aliased boundary, under 2 px from both) included."""
    kernel = np.ones((2 * FRINGE_PX + 1, 2 * FRINGE_PX + 1), np.uint8)
    near_white = cv2.dilate(white.astype(np.uint8), kernel).astype(bool)
    near_loose = cv2.dilate(loose.astype(np.uint8), kernel).astype(bool)
    return (loose | white | (near_white & near_loose)).mean(axis=1) >= PAD_EMPTY_SHARE


def _run(band: np.ndarray, empty: np.ndarray, rule: EdgeRule, dpi: int) -> tuple[int, int] | None:
    """The first and one past the last row of the band in ``band`` (band rows, edge first), or
    None unless it starts within reach over empty rows and is neither too short nor too long."""
    hits = np.flatnonzero(band)
    if not hits.size or hits[0] > mm_to_px(rule.reach_mm, dpi) or not empty[: hits[0]].all():
        return None
    start = int(hits[0])
    gaps = np.flatnonzero(~band[start:])
    if not gaps.size:
        return None
    end = start + int(gaps[0])
    long_enough = mm_to_px(rule.min_mm, dpi) <= end - start <= mm_to_px(rule.max_mm, dpi)
    return (start, end) if long_enough else None


def band_cut(pixels: np.ndarray, dpi: int, rule: EdgeRule) -> Band | None:
    """The band at the edge ``rule`` is for, or None when the page has none there.

    ``pixels`` is a colour page. The cut never goes into the edge line, and not into the shadow
    next to the paper where it is darker than backing: the rows of the last 4 mm of the band in
    which under 95% of the pixels are backing (within the tolerance of ``trim``) stay.
    """
    window = _edge_first(pixels, rule, dpi)
    loose = backing_mask(window, SHADOW_TOLERANCE)
    white = window.min(axis=2) >= PAD_WHITE_MIN
    found = _run(loose.mean(axis=1) >= BAND_SHARE, _empty_rows(loose, white), rule, dpi)
    if found is None:
        return None
    start, end = found
    zone = max(start, end - mm_to_px(SHADOW_ZONE_MM, dpi))
    dark = np.flatnonzero(backing_mask(window[zone:end]).mean(axis=1) < BAND_SHARE)
    clean = end if not dark.size else zone + int(dark[0])
    keep = mm_to_px(rule.keep_mm, dpi) if rule.keep_mm else 0
    cut = max(0, min(end - keep, clean))
    clear = np.flatnonzero(white[:end].mean(axis=1) < PAD_ROW_SHARE)  # rows with no pad left
    if not clear.size:
        return None
    pad = int(clear[0]) + PAD_MARGIN_PX if clear[0] else 0  # the pad that touches the frame's edge
    return Band(cut, min(pad, cut))
