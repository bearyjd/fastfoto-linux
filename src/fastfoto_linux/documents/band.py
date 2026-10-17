"""The scanner's backing band below and above the paper: where the paper ends on real pages.

A raw frame is full length: the paper, its band, then a white tail of about 98 mm. The scanner
straightens the paper by rotating the frame (1 to 3 degrees), so the pad of pure white, which is
everything outside the rotated scan, is a slanted lower edge and the pad also forms wedges up the
sides (14 mm wide at 3 degrees); the page is a JPEG, which rings around the pad's edge. From the
bottom edge of the scan upward: the slanted pad (a row passes from nearly all pad to none within
about 10 mm), a full-width backing band of 6 to 15 mm in the backing colour of ``pipeline.crop``,
darker next to the paper (a shadow, up to 1 mm), an optional edge line of about 1 mm, then the
paper, which is often pure 255 like the pad and so cannot be told from it by its brightness. At
the top there are at most 2 mm of the same backing, the edge line, the paper. The full-width
backing band is the reliable sign of where the paper ends.

* The frame has a tail, so the band is looked for above the white tail: ``trim`` gives this
  module the page down to where the tail starts, and the tail goes with the band.
* Rows are judged by what is not white (white is every channel at 240 or more: the pad, the paper
  at 250 to 255, the ringing next to the pad's edge): a band row has non-white pixels on at least
  50% of its width and backing on at least 95% of those, so the wedges of pad in a row do not hide
  the backing. Pixels that are neither white nor backing but within 2 px of white are the pad's
  blurred edge and count for neither. A row with more than 10 mm of white that touches neither
  side of the row (a white slip, a narrow item) is not a band row; a gap of a few pixels does
  not split a run of white.
* The band is the first run of band rows going up from the bottom of that page, with only pad rows
  (under 50% non-white) below it, starting within 20 mm of its edge: a band of 3 to 20 mm at the
  bottom and of 1 to 4 mm at the top (within 0.5 mm of the top edge). The least counts from the
  middle of the pad's slant, the most from where the slant ends. A longer run (a backing-coloured
  header or form margin) is not a band and nothing is cut. The run ends at the first row that
  is not a band row and never extends into the white rows above it, because the paper can be
  pure 255.
* The cut is made at the band's border with the paper, never through the edge line: the edge line
  is not backing, so it ends the run and is kept whole. At least 1 mm of the band stays at the
  bottom (none at the top), and up to ~4 mm when the shadow next to the paper is dark: the shadow
  is darker than what the last check in ``guard`` calls backing (within 20 of the backing
  colour), so the cut never takes a row of the last 4 mm of the band in which that is not backing
  in 95% of the non-white pixels.
* At least 30 mm of page stay after each cut, and the last check in ``guard`` applies to the
  strip that is cut: the band, the slanted pad under it and the first 3 mm of the white tail,
  where the pad's edge rings. Ink anywhere in the rest of the tail keeps the page (the ink search
  of the tail rule), so the white of the tail joins nothing to a side. In the strip pad pixels
  are exempt one by one: white, and the pixels within 2 px of both white and backing, where the
  pad's edge passes into the backing. Backing is within 20 of the backing colour, as in the side
  strips and the tail, and counts only where it is joined to a side of the strip or to its first
  row, the band next to the cut, by backing alone: the pad joins nothing, so a separate island of
  the backing's colour, on the pad or in the tail, is not the band. The shadow gets more: a
  cluster of tone within 36 of the backing colour (``SHADOW_TOLERANCE``, as for the rows) is
  backing where the shadow lies, in the first 1.5 mm of the strip, next to the cut, and within
  2 px of the pad (the edge of a wedge), and only when it is under 2 mm long and bluer than red
  by at most 24 on average: the backing and its shadow are (17 and 14), a faded blue ink or a
  bluish pencil on a slip of the backing's colour is not (30 to 40). A pale bar, a stroke of pale
  ink or a slip in that tone is longer and keeps the page. A cluster under 0.5 mm whose pixels
  are all within 50 of the backing colour, of any hue, is dust. Every other pixel goes to the last
  check; a mark that is darker, not blue or beyond that tolerance, ink bluer than the shadow, and
  dust of ink size in the pad, keep the page, as in the tail. A light vertical line up to 0.3 mm
  wide counts as backing too (``streak``): a fleck on the scanner's glass or backing, at least 4
  levels brighter, in every channel, than the backing beside it, its blue minus red within 12 of
  the backing's, in at least 90% of the rows that have backing on both sides of it, over at least
  3 mm of such rows; with its blurred edge it joins the parts of the band it splits, whatever the
  pad and the shadow do at their sides, and a mark that crosses it stays whole. Below 170 dpi the
  rule is off.
* After a band cut the new edge is the paper's, so the blank-page margin is measured in full
  from the new edge (``Trimmed.tail_rows``): the kept edge line is margin, not a mark.

Only colour pages are looked at: grey and 1-bit pages are not cut by the band rule (a grey page
has no hue to tell the backing by). Limits, stated exactly:

* Side slivers of up to 2 mm are left, because they are slanted and the strip rule needs 3 mm.
* A bar at least half the page wide within 20 of the backing colour, flush with the paper's end
  and with no shadow below it, is cut with the band, as a full-height sidebar of that colour is
  at a side, and with it what is in it in the band's own hue (bluer than red by at most 24). The
  band's shadow below the bar keeps it, being beyond the 1.5 mm of the strip; so does ink in
  another hue, and a bar in a blue-grey between 20 and 36 from the backing colour.
* Pale ink or pencil within 1.5 mm of the cut on a slip of the backing's colour is forgiven as
  shadow when its strokes are under 2 mm and, mixed with the slip by the blur, its tone is within
  36 of the backing colour and bluer than red by at most 24. The hue gate is one-sided: it keeps
  out ink bluer than that, but neutral grey passes it (a pencil stroke 1 pixel wide of tone 170
  or lighter, or 2 pixels wide of 190 or lighter, is cut with the band; a stroke 3 pixels wide
  only when lighter than about 190, or about 184 right at the cut).
* Specks under 0.5 mm within 50 of the backing colour in the strip are dust: 0.4 mm dots on a
  slip are cut with it.
* A dark streak keeps the strip: ink darkens, so only a lighter line is forgiven (clean the
  scanner, glass and backing). A light vertical line up to 0.3 mm wide down the whole band is taken
  for the scanner's, a little wider with its blurred edge (a line painted 4 pixels wide at 200 dpi,
  5 at 300 and 9 at 600 is still one); a light line of 0.7 mm or more, a light streak over under
  90% of the rows, one that leans across the band (3 degrees moves it 0.6 mm) and, at the top, a
  band under 3 mm tall keep the strip. A streak 1 pixel wide never was a problem (the blur brings
  it within 20 of the backing), a line of pure white is pad, and a side strip has no streak rule.
  A blank slip of the backing's colour that touches a streak goes with the band, as one that
  touches the band does; a slip with anything on it keeps the strip.
* A scrap of the backing's colour that touches the band is taken for the band.
* A scrap of the backing's colour that touches a side of the page in the first 3 mm of the white
  tail, which are part of the strip, is joined to the side by backing alone and goes with the
  band; further down the ink search of the tail rule finds it and the page is kept, and so is a
  scrap that touches neither a side nor the band.
* The last pixel row or two of a glyph whose bottom lies in the band rows may go (0.04 to
  0.13 mm).
"""

from dataclasses import dataclass

import cv2
import numpy as np

from fastfoto_linux.documents.units import mm_to_px
from fastfoto_linux.pipeline.crop import BACKGROUND_PRIOR_RGB, BACKGROUND_PRIOR_TOLERANCE

BAND_SHARE = 0.95  # a band row is at least this share backing, of its non-white pixels
COLOURED_SHARE = 0.5  # and has non-white pixels on at least this share of its width (else: pad)
SHADOW_TOLERANCE = 36  # a shadow pixel is at most this far from the backing colour (RGB)
WHITE_MIN = 240  # white: every channel at least this (pad 255, paper 250 to 255, codec ringing)
HOLE_MM = 10.0  # a band row has no more white than this that touches neither of its sides
FRINGE_PX = 2  # where the pad and the backing blend, a pixel lies this close to white
TAPER_SHARE = 0.02  # the pad's slant is over when the share of white is this near its lowest
SHADOW_ZONE_MM = 4.0  # the shadow lies in this much of the band next to the paper
WINDOW_SLACK_MM = 1.0  # rows looked at beyond the longest band (the paper, to see its end)

_PRIOR = np.asarray(BACKGROUND_PRIOR_RGB, dtype=np.float32)


@dataclass(frozen=True)
class EdgeRule:
    """Where to look for a band and how big it may be (all in millimetres)."""

    bottom: bool
    reach_mm: float  # the band starts at most this far from the edge of the page it is given
    min_mm: float
    max_mm: float
    keep_mm: float  # of the band stays next to the paper


BOTTOM_EDGE = EdgeRule(bottom=True, reach_mm=20.0, min_mm=3.0, max_mm=20.0, keep_mm=1.0)
# the first row at the top is partly pad, not a band row: a band of 1 mm is a run a little shorter
TOP_EDGE = EdgeRule(bottom=False, reach_mm=0.5, min_mm=0.75, max_mm=4.0, keep_mm=0.0)


def backing_distance(colours: np.ndarray) -> np.ndarray:
    """For every colour (last axis RGB): its RGB distance from the measured background."""
    return np.linalg.norm(colours.astype(np.float32) - _PRIOR, axis=-1)


def backing_mask(colours: np.ndarray, tolerance: float = BACKGROUND_PRIOR_TOLERANCE) -> np.ndarray:
    """For every colour (last axis RGB): is it the scanner's backing, blue-grey and within
    ``tolerance`` of the measured background? Cream or neutral grey is never backing."""
    return (backing_distance(colours) <= tolerance) & (colours[..., 2] > colours[..., 0])


def _edge_first(pixels: np.ndarray, rule: EdgeRule, dpi: int) -> np.ndarray:
    """The rows of ``pixels`` next to the edge the rule is for, the row on the edge first."""
    rows = mm_to_px(rule.reach_mm + rule.max_mm + WINDOW_SLACK_MM, dpi)
    return pixels[::-1][:rows] if rule.bottom else pixels[:rows]


def _blur_of_pad(loose: np.ndarray, white: np.ndarray) -> np.ndarray:
    """Pixels that are neither white nor backing but lie within ``FRINGE_PX`` of white: the
    anti-aliased and ringing edge of the pad. They count for neither side of a row's share."""
    kernel = np.ones((2 * FRINGE_PX + 1, 2 * FRINGE_PX + 1), np.uint8)
    near_white = cv2.dilate(white.astype(np.uint8), kernel).astype(bool)
    return near_white & ~white & ~loose


def _interior_white(white: np.ndarray) -> np.ndarray:
    """Per row: the white pixels that are not in the run of white at either end of the row. A gap
    of a few pixels in a run (a speck, the codec's ringing) does not split it."""
    kernel = np.ones((1, 2 * FRINGE_PX + 1), np.uint8)
    closed = cv2.morphologyEx(white.astype(np.uint8), cv2.MORPH_CLOSE, kernel).astype(bool)
    whole = closed.all(axis=1)
    width = closed.shape[1]
    lead = np.where(whole, width, closed.argmin(axis=1))
    trail = np.where(whole, width, closed[:, ::-1].argmin(axis=1))
    return np.maximum(closed.sum(axis=1) - lead - trail, 0)


def _band_rows(backing: np.ndarray, white: np.ndarray, dpi: int) -> tuple[np.ndarray, np.ndarray]:
    """Which rows are band rows, and which are pad rows (under ``COLOURED_SHARE`` of the width
    is non-white). A band row has non-white pixels on at least that share, ``BAND_SHARE`` of them
    ``backing``, and no white slip in the middle of the row."""
    coloured = ~white & ~_blur_of_pad(backing, white)
    count = coloured.sum(axis=1)
    mostly = count >= COLOURED_SHARE * white.shape[1]
    band = (
        mostly
        & ((backing & coloured).sum(axis=1) >= BAND_SHARE * count)
        & (_interior_white(white) <= mm_to_px(HOLE_MM, dpi))
    )
    return band, ~mostly


def _settled(white: np.ndarray, start: int, end: int) -> int:
    """The first row of the run ``start:end`` after the pad's slanted edge: where the share of
    white stops falling (it stays at the side wedges' share, if any). The slant is not band."""
    share = white[start:end].mean(axis=1)
    return start + int(np.argmax(share <= share.min() + TAPER_SHARE))


def _run(
    band: np.ndarray, pad: np.ndarray, white: np.ndarray, rule: EdgeRule, dpi: int
) -> tuple[int, int] | None:
    """The first and one past the last row of the band in ``band`` (band rows, edge first), or
    None unless it starts within reach over pad rows, is at least ``min_mm`` long from the middle
    of the pad's slant, and is at most ``max_mm`` long from where the slant ends."""
    hits = np.flatnonzero(band)
    if not hits.size or hits[0] > mm_to_px(rule.reach_mm, dpi) or not pad[: hits[0]].all():
        return None
    start = int(hits[0])
    gaps = np.flatnonzero(~band[start:])
    if not gaps.size:
        return None
    end = start + int(gaps[0])
    thick = mm_to_px(rule.min_mm, dpi) <= end - start
    short = end - _settled(white, start, end) <= mm_to_px(rule.max_mm, dpi)
    fits = thick and short
    return (start, end) if fits else None


def band_cut(pixels: np.ndarray, dpi: int, rule: EdgeRule) -> int | None:
    """Rows to cut from the edge ``rule`` is for, or None when the page has no band there.

    ``pixels`` is a colour page (at the bottom: down to where the white tail starts). The cut
    never goes into the edge line, and not into the shadow next to the paper where it is darker
    than backing: the rows of the last 4 mm of the band in which under 95% of the non-white
    pixels are backing (within the tolerance of ``trim``) stay.
    """
    window = _edge_first(pixels, rule, dpi)
    white = window.min(axis=2) >= WHITE_MIN
    band, pad = _band_rows(backing_mask(window, SHADOW_TOLERANCE), white, dpi)
    found = _run(band, pad, white, rule, dpi)
    if found is None:
        return None
    start, end = found
    zone = max(start, end - mm_to_px(SHADOW_ZONE_MM, dpi))
    tight, _ = _band_rows(backing_mask(window[zone:end]), white[zone:end], dpi)
    dark = np.flatnonzero(~tight)
    clean = end if not dark.size else zone + int(dark[0])
    keep = mm_to_px(rule.keep_mm, dpi) if rule.keep_mm else 0
    return max(0, min(end - keep, clean)) or None
