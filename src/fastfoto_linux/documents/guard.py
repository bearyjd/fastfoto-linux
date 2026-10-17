"""The last check on every strip a trim would remove: is there anything in it but blank white and
the scanner's backing? A cut is cancelled when the strip holds a cluster of ink size that is
neither (the rules, and what the trim does about it, are in ``trim``).

The check runs on a blurred copy (3x3), so that noise makes no clusters of its own and a dot of
two or three pixels grows into one. A band cut's strip (``pad=True``, its first row next to the
cut) is judged with the scanner's pad exempt pixel by pixel. Backing is within
``BACKGROUND_PRIOR_TOLERANCE`` of the measured colour and joined to a side of the strip by backing
alone, in a band strip also to its first row, the band: the pad joins nothing, so a separate
island of the backing's colour is not the band. The band darkens towards the paper, so shadow tone
(up to ``SHADOW_TOLERANCE``, blue over red) is backing too, only where the shadow lies: in the
first ``SHADOW_STRIP_MM`` of the strip, next to the cut, and within ``FRINGE_PX`` of the pad's
edge, and only in clusters shorter than ``SHADOW_CLUSTER_MM`` (a longer run of that tone is a bar
or a stroke of ink, not a speck) and in the backing's hue: a cluster whose mean blue minus red is
over ``SHADOW_BLUE_MAX`` is faded blue ink or bluish pencil, not shadow (the gate is one-sided:
neutral grey passes it). A cluster shorter than ``DUST_MM`` whose pixels are all within
``DUST_TOLERANCE`` of the backing colour, whatever the hue, is dust. A light vertical line up to
0.3 mm wide down the band, the scanner's own streak (see ``streak``: lighter in every channel and
of the backing's tint), is backing too and joins the parts of the band it splits, and a mark that
crosses it stays whole; a dark streak is not, and keeps the strip. A blank slip of the backing's
colour that touches a streak goes with the band, one with anything on it does not.
"""

import math

import cv2
import numpy as np

from fastfoto_linux.documents.band import (
    FRINGE_PX,
    SHADOW_TOLERANCE,
    WHITE_MIN,
    backing_distance,
    backing_mask,
)
from fastfoto_linux.documents.streak import with_streak
from fastfoto_linux.documents.units import MM_PER_INCH, mm_to_px
from fastfoto_linux.imaging import RGB_NDIM
from fastfoto_linux.pipeline.crop import BACKGROUND_PRIOR_TOLERANCE

INK_DEVIATION = 12  # levels darker than the tail's white: 4x its noise, far under any pencil
INK_CLUSTER_MM = 0.3  # the longer side of a cluster that counts (dust is smaller)
INK_CLUSTER_MIN_PX = 2  # one pixel is noise at any resolution; 0.3 mm is rounded up to pixels
GUARD_BLUR_PX = 3  # the colour tests run on a copy blurred over this many pixels (noise, dots)
SHADOW_STRIP_MM = 1.5  # the shadow's specks are forgiven in this much of the strip next to the cut
SHADOW_CLUSTER_MM = 2.0  # a cluster of shadow tone is a speck only when it is shorter than this
DUST_MM = 0.5  # a pale cluster shorter than this, anywhere in the strip, is dust
DUST_TOLERANCE = 50  # and pale means this near the backing colour (RGB, any hue)
SHADOW_BLUE_MAX = 24  # shadow is forgiven if its blue minus red is at most this (ink: 30+)


def grey_of(pixels: np.ndarray) -> np.ndarray:
    """The darkest channel of every pixel (the page itself when it is grey)."""
    return pixels.min(axis=2) if pixels.ndim == RGB_NDIM else pixels


def _size_px(mm: float, dpi: int) -> int:
    """``mm`` rounded up to whole pixels, so that nothing shorter than that reaches it."""
    return math.ceil(mm * dpi / MM_PER_INCH)


def ink_size_px(dpi: int) -> int:
    """Pixels in the longer side of the smallest ink cluster: ``INK_CLUSTER_MM`` rounded up, so
    that nothing shorter than that counts (at 200 dpi 0.3 mm is 3 pixels, not 2)."""
    return max(INK_CLUSTER_MIN_PX, _size_px(INK_CLUSTER_MM, dpi))


def _clusters(mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The 8-connected clusters of ``mask``: the label of every pixel (0: none), and the longer
    side of each cluster, indexed by label (0 for none)."""
    _, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    longest = np.maximum(stats[:, cv2.CC_STAT_WIDTH], stats[:, cv2.CC_STAT_HEIGHT])
    longest[0] = 0
    return labels, longest


def ink_clusters(mask: np.ndarray, dpi: int) -> np.ndarray:
    """The boxes (OpenCV statistics rows) of the clusters of ``mask`` that are ink-sized."""
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    boxes = stats[1:count]  # row 0 is the background
    longest = np.maximum(boxes[:, cv2.CC_STAT_WIDTH], boxes[:, cv2.CC_STAT_HEIGHT])
    return boxes[longest >= ink_size_px(dpi)]


def joined_to_sides(tone: np.ndarray, *, first_row: bool = False) -> np.ndarray:
    """The part of ``tone`` that is connected to the left or the right edge of the array, and
    with ``first_row`` to its first row: the backing runs in from the side of the frame, a note
    lying in the strip does not."""
    count, labels = cv2.connectedComponents(tone.astype(np.uint8), connectivity=8)
    joined = np.zeros(count, dtype=bool)
    joined[labels[:, 0]] = True
    joined[labels[:, -1]] = True
    if first_row:
        joined[labels[0]] = True
    joined[0] = False  # label 0 is what is not ``tone``
    return joined[labels]


def backing_pixels(
    strip: np.ndarray, tolerance: float | None = None, *, band: bool = False, dpi: int | None = None
) -> np.ndarray:
    """Which pixels of ``strip`` are the scanner's backing and so need no keeping.

    On a colour page: backing-coloured (within ``tolerance``, the scanner's by default) and
    joined to a side of the strip by backing alone. In the strip of a band cut (``band``) the
    first row, next to the cut, is the band's own backing and joins as a side does; the pad does
    not join anything: a separate island of the backing's colour is not the band, however close
    to it. A light streak down the band (see ``streak``, which needs ``dpi``) is backing too, and
    joins the parts of the band it splits; where a mark crosses it, the pixels that the blur makes
    look like backing are not. A grey page has no hue, and a pale slip or a pastel
    margin looks just like the backing wherever it lies, so on a grey page nothing is backing.
    """
    if strip.ndim != RGB_NDIM:
        return np.zeros(strip.shape, dtype=bool)
    backing = backing_mask(strip, BACKGROUND_PRIOR_TOLERANCE if tolerance is None else tolerance)
    if band:
        if dpi is None:
            raise ValueError("dpi is needed to look for a streak in the strip of a band cut")
        backing = with_streak(backing, strip, dpi)
    return joined_to_sides(backing, first_row=band)


def blended(white: np.ndarray, backing: np.ndarray) -> np.ndarray:
    """Pixels within ``FRINGE_PX`` of both white and backing: where a blurred edge between the
    two is neither, and where a slip or a stroke, which borders only one of them, is not."""
    return _near(white) & _near(backing)


def _near(mask: np.ndarray) -> np.ndarray:
    """``mask`` grown by ``FRINGE_PX`` in every direction."""
    kernel = np.ones((2 * FRINGE_PX + 1, 2 * FRINGE_PX + 1), np.uint8)
    return cv2.dilate(mask.astype(np.uint8), kernel).astype(bool)


def pad_pixels(strip: np.ndarray) -> np.ndarray:
    """The scanner's pad in the unblurred ``strip``: white, and the pixels within ``FRINGE_PX`` of
    both white and backing, where the pad's edge (anti-aliasing, the codec's ringing, a wedge
    thinner than the blur) passes into the backing. Judged pixel by pixel, not row by row."""
    white = strip.min(axis=2) >= WHITE_MIN
    return white | blended(white, backing_mask(strip))


def _shadow_places(pad: np.ndarray, dpi: int) -> np.ndarray:
    """Where the band's shadow lies in a band strip: its first rows, next to the cut, and the
    edge of the pad."""
    places = _near(pad)
    places[: mm_to_px(SHADOW_STRIP_MM, dpi)] = True
    return places


def _shorter_than(mask: np.ndarray, limit_px: int) -> np.ndarray:
    """The clusters of ``mask`` whose longer side is under ``limit_px``."""
    labels, longest = _clusters(mask)
    return ((longest > 0) & (longest < limit_px))[labels]


def _dust(unexplained: np.ndarray, smooth: np.ndarray, dpi: int) -> np.ndarray:
    """The clusters of ``unexplained`` that are dust: under ``DUST_MM`` and every pixel within
    ``DUST_TOLERANCE`` of the backing colour."""
    labels, longest = _clusters(unexplained)
    far = unexplained & (backing_distance(smooth) > DUST_TOLERANCE)
    has_far = np.zeros(len(longest), dtype=bool)
    has_far[labels[far]] = True
    return ((longest > 0) & (longest < _size_px(DUST_MM, dpi)) & ~has_far)[labels]


def _in_shadow_hue(clusters: np.ndarray, smooth: np.ndarray) -> np.ndarray:
    """The clusters of ``clusters`` whose mean blue minus red on ``smooth`` is at most
    ``SHADOW_BLUE_MAX``: the shadow is the backing's own blue-grey, a faded blue ink or a bluish
    pencil on a slip is bluer."""
    labels, longest = _clusters(clusters)
    ids = labels[clusters]
    size = np.maximum(np.bincount(ids, minlength=len(longest)), 1)
    blue = np.bincount(ids, smooth[..., 2][clusters], minlength=len(longest))
    red = np.bincount(ids, smooth[..., 0][clusters], minlength=len(longest))
    return ((blue - red) / size <= SHADOW_BLUE_MAX)[labels] & clusters


def _shadow_backing(
    smooth: np.ndarray, pad: np.ndarray, strict: np.ndarray, dpi: int
) -> np.ndarray:
    """The pixels of shadow tone that count as backing in a band strip: within the band's
    tolerance, where the shadow lies, in the backing's hue, in clusters short enough for a
    speck."""
    wide = backing_pixels(smooth, SHADOW_TOLERANCE, band=True, dpi=dpi) & ~strict
    specks = _shorter_than(wide & _shadow_places(pad, dpi), _size_px(SHADOW_CLUSTER_MM, dpi))
    return _in_shadow_hue(specks, smooth)


def holds_content(strip: np.ndarray, white: float, dpi: int, *, pad: bool = False) -> bool:
    """Does ``strip``, which a trim would remove, hold an ink-sized cluster that is neither
    blank white (less than ``INK_DEVIATION`` darker than ``white``) nor backing?

    With ``pad`` (a colour strip of the band cut, its first row next to the cut) the pad's pixels
    are exempt one by one, the backing may join a side through them, and the band's shadow and
    dust are forgiven, as described above.
    """
    smooth = cv2.boxFilter(strip, cv2.CV_32F, (GUARD_BLUR_PX, GUARD_BLUR_PX))
    marked = grey_of(smooth) <= white - INK_DEVIATION
    if not marked.any():
        return False
    exempt = pad_pixels(strip) if pad else None
    backing = backing_pixels(smooth, band=pad, dpi=dpi)
    if exempt is not None:
        backing = backing | _shadow_backing(smooth, exempt, backing, dpi)
    unexplained = marked & ~backing & ~blended(~marked, backing)
    if exempt is not None:
        unexplained &= ~exempt
        unexplained &= ~_dust(unexplained, smooth, dpi)
    return bool(ink_clusters(unexplained, dpi).size)
