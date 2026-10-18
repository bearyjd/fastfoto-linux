"""A coarse map of the dark on a page, to tell ink that comes from a neighbouring sheet.

Bleed-through from the sheet beneath (or above) is not a clean copy: its marks lie a few mm off
where the print is mirrored and are not the same shape, so the shape match of ``bleed`` misses
it. What it does show is that the marks of a back lie where the printed side of the neighbour
has print. Each page keeps ``ink_map``: one bit per cell of ``MAP_DPI`` (about 5 KB for Letter;
a cell is dark when any pixel in it is darker than ``INK_TONE``), never the pixels.

``hit_rates``: the share of a back's marks whose centre, mirrored (the back is the front flipped
left to right within the scanner's frame, each page's trim offset added back), falls within
``REACH_MM`` of a dark cell of the source's map (``hit``), and the same share with the source
shifted ``CONTROL_SHIFT_MM`` in each direction (``control``: how often a mark would land on that
page's print by chance, high on dense text). ``lies_on``: at least ``MARKS_MIN`` marks, ``hit``
at least ``HIT_MIN`` and ``hit`` less ``control`` at least ``ADVANTAGE_MIN``.

A flag from this is a hint to look at the page ("looks like bleed-through: check"); it never drops
or keeps a page, so a false alarm is cheap and a miss is not. The accepted trade-offs: a short
note that lies on dense print (hit 1.0, control 0.75) is flagged; and on very dense pages a
control of 0.85 or more leaves less than ``ADVANTAGE_MIN`` whatever the hit, so a ghost there is
not flagged.
"""

import math
from collections.abc import Sequence

import cv2
import numpy as np

from fastfoto_linux.documents.draft import BoxN, InkMap
from fastfoto_linux.documents.trim import Trimmed
from fastfoto_linux.documents.units import MM_PER_INCH
from fastfoto_linux.imaging import RGB_NDIM

MAP_DPI = 20  # one cell is 1.27 mm square
INK_TONE = 120  # a pixel darker than this (darkest colour channel) is ink
REACH_MM = 3.0  # a mark is on print when a dark cell lies within this of its mirrored centre
CONTROL_SHIFT_MM = 20.0  # the control looks this far off, up, down, left and right
HIT_MIN = 0.9  # at least this share of the marks lies on print
ADVANTAGE_MIN = 0.2  # ... and at least this much more than the control (a hint: see above)
MARKS_MIN = 3  # fewer marks than this are left to the shape match of ``bleed``


def ink_map(page: Trimmed) -> InkMap:
    """The coarse ink map of a trimmed page."""
    pixels = page.page.pixels
    height, width = pixels.shape[:2]
    dpi = page.page.dpi
    grey = pixels.min(axis=2) if pixels.ndim == RGB_NDIM else pixels
    dark = (grey < INK_TONE).astype(np.float32)
    step = dpi / MAP_DPI
    cols, rows = math.ceil(width / step), math.ceil(height / step)
    cells = cv2.resize(dark, (cols, rows), interpolation=cv2.INTER_AREA) > 0
    mm = MM_PER_INCH / dpi
    return InkMap(
        bits=np.packbits(cells.ravel()).tobytes(),
        cols=cols,
        rows=rows,
        cell_mm=MM_PER_INCH / MAP_DPI,
        left_mm=page.left * mm,
        top_mm=page.top * mm,
        width_mm=width * mm,
        height_mm=height * mm,
        frame_mm=(width + page.left + page.right) * mm,
    )


def _cells(ink: InkMap) -> np.ndarray:
    flat = np.unpackbits(np.frombuffer(ink.bits, dtype=np.uint8), count=ink.cols * ink.rows)
    return flat.reshape(ink.rows, ink.cols).astype(np.uint8)


def _near_dark(ink: InkMap) -> np.ndarray:
    """The cells within ``REACH_MM`` of a dark one."""
    radius = round(REACH_MM / ink.cell_mm)
    kernel = np.ones((2 * radius + 1, 2 * radius + 1), np.uint8)
    return cv2.dilate(_cells(ink), kernel) > 0


def _rate(near: np.ndarray, source: InkMap, spots: np.ndarray, shift: tuple[float, float]) -> float:
    """The share of the ``spots`` (mm in the source's page) that lie on a cell of ``near`` once
    moved by ``shift``; a spot off the page lies on nothing."""
    cols = np.floor((spots[:, 0] + shift[0]) / (source.width_mm / source.cols)).astype(int)
    rows = np.floor((spots[:, 1] + shift[1]) / (source.height_mm / source.rows)).astype(int)
    inside = (cols >= 0) & (cols < source.cols) & (rows >= 0) & (rows < source.rows)
    hits = np.zeros(len(spots), dtype=bool)
    hits[inside] = near[rows[inside], cols[inside]]
    return float(hits.mean())


def hit_rates(marks: Sequence[BoxN], back: InkMap, source: InkMap) -> tuple[float, float]:
    """``(hit, control)`` of the ``marks`` of ``back`` against the ink map of ``source`` (see the
    module's text); (0, 0) without marks."""
    if not marks:
        return 0.0, 0.0
    centres = np.array(
        [
            [(box.x0 + box.x1) / 2 * back.width_mm, (box.y0 + box.y1) / 2 * back.height_mm]
            for box in marks
        ]
    )
    spots = np.empty_like(centres)
    spots[:, 0] = back.frame_mm - (back.left_mm + centres[:, 0]) - source.left_mm
    spots[:, 1] = back.top_mm + centres[:, 1] - source.top_mm
    near = _near_dark(source)
    far = CONTROL_SHIFT_MM
    shifts = ((0.0, far), (0.0, -far), (far, 0.0), (-far, 0.0))
    control = float(np.mean([_rate(near, source, spots, shift) for shift in shifts]))
    return _rate(near, source, spots, (0.0, 0.0)), control


def lies_on(marks: Sequence[BoxN], back: InkMap, source: InkMap) -> bool:
    """Whether the marks of ``back`` lie where ``source`` is printed, mirrored."""
    if len(marks) < MARKS_MIN:
        return False
    hit, control = hit_rates(marks, back, source)
    return hit >= HIT_MIN and hit - control >= ADVANTAGE_MIN
