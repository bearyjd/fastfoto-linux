"""Sheets with holes through the paper, for the hole tests: the two sides of one sheet.

A hole shows as a dark mark at the same physical spot on both sides, so on the page images it
lies mirrored left to right: the back of a sheet is its front flipped, and the top stays on top.
``sheet`` makes both sides from one description: where the paper lies in the scanner's frame
(the front's gap at the left is the back's gap at the right), how far the back is off the front
(a shift and a small rotation: the feeder and the deskew), and what is drawn on each side, in mm
from the paper's top left corner. Every side goes through JPEG last, as a scan does.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

import cv2
import numpy as np

from tests.doc_synth import INK_TONE, LETTER_MM, Scene, paper_scene, px
from tests.doc_synth_band import with_jpeg

HOLE_TONE = 110  # the dark backing seen through a hole: a neutral dark grey
Tone = int | tuple[int, int, int]  # a grey level, or a colour (red, green, blue)
SMALL_MM = (100.0, 120.0)  # a small sheet keeps 600 dpi fast
Painter = Callable[[Scene], Scene]

# Seven-segment digits (no fonts are needed): the segments that each digit lights.
SEGMENTS = {
    "0": "abcdef",
    "1": "bc",
    "2": "abged",
    "3": "abgcd",
    "4": "fgbc",
    "5": "afgcd",
    "6": "afgedc",
    "7": "abc",
    "8": "abcdefg",
    "9": "abcdfg",
}
DIGIT_MM = (1.8, 3.2)  # width and height of a digit
DIGIT_STROKE_MM = 0.45
DIGIT_PITCH_MM = 2.6


@dataclass(frozen=True)
class Hole:
    """A dark spot (a dash, an ellipse if ``round`` and a ring of ``ring_mm`` if that is set, or a
    stroke across its box if ``slope`` is +1 for "/" and -1 for "\\") with its top left corner in
    mm from the paper's top left corner."""

    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float
    round: bool = False
    slope: int = 0
    stroke_mm: float = 0.7  # the width of a slanted stroke
    ring_mm: float = 0.0  # the thickness of a ring (an "o", a "0"); 0 is a filled spot

    def mirrored(self, paper_width_mm: float) -> "Hole":
        """The same hole as the other side of the paper shows it: flipped left to right."""
        return replace(self, x_mm=paper_width_mm - self.x_mm - self.width_mm, slope=-self.slope)

    def flipped_down(self, paper_height_mm: float) -> "Hole":
        """The hole flipped top to bottom: where it is NOT on the other side of a sheet."""
        return replace(self, y_mm=paper_height_mm - self.y_mm - self.height_mm, slope=-self.slope)

    def moved(self, dx_mm: float = 0.0, dy_mm: float = 0.0) -> "Hole":
        return replace(self, x_mm=self.x_mm + dx_mm, y_mm=self.y_mm + dy_mm)


def dash(x_mm: float, y_mm: float, length_mm: float, thickness_mm: float = 0.7) -> Hole:
    return Hole(x_mm, y_mm, length_mm, thickness_mm)


def disc(x_mm: float, y_mm: float, diameter_mm: float) -> Hole:
    return Hole(x_mm, y_mm, diameter_mm, diameter_mm, round=True)


def ring(x_mm: float, y_mm: float, diameter_mm: float, thickness_mm: float) -> Hole:
    """An "o": a round outline of ``thickness_mm`` that is hollow inside."""
    return Hole(x_mm, y_mm, diameter_mm, diameter_mm, round=True, ring_mm=thickness_mm)


def slanted(x_mm: float, y_mm: float, length_mm: float, slope: int = 1) -> Hole:
    """A stroke across a square box of ``length_mm``: "/" for slope +1, "\\" for -1."""
    return Hole(x_mm, y_mm, length_mm, length_mm, slope=slope)


# Staple holes near a top corner: 12 to 18 mm from the left, 6 mm from the top.
STAPLES = (dash(12.0, 6.0, 1.8), dash(14.6, 6.4, 1.5, 0.8), disc(16.8, 5.8, 1.2))
# Punched holes: three 6 mm discs near the left edge.
PUNCHES = (disc(8.0, 20.0, 6.0), disc(8.0, 55.0, 6.0), disc(8.0, 90.0, 6.0))


def with_holes(scene: Scene, holes: Sequence[Hole], tone: Tone = HOLE_TONE) -> Scene:
    """``holes`` drawn in ``tone``. They are not content: a hole is not writing."""
    image = scene.image.copy()
    for hole in holes:
        left = scene.paper_x[0] + px(hole.x_mm, scene.dpi)
        top = scene.paper_top + px(hole.y_mm, scene.dpi)
        right, bottom = left + px(hole.width_mm, scene.dpi), top + px(hole.height_mm, scene.dpi)
        if hole.round or hole.slope:
            canvas = np.zeros(image.shape[:2], np.uint8)
            if hole.round:
                centre = ((left + right) // 2, (top + bottom) // 2)
                axes = ((right - left) // 2, (bottom - top) // 2)
                thickness = px(hole.ring_mm, scene.dpi) if hole.ring_mm else -1
                if thickness > 0:  # the outline is drawn half in, half out of the ellipse
                    axes = (axes[0] - thickness // 2, axes[1] - thickness // 2)
                cv2.ellipse(canvas, centre, axes, 0, 0, 360, 1, thickness)
            else:
                ends = ((left, bottom - 1), (right - 1, top))  # "/"
                if hole.slope < 0:
                    ends = ((left, top), (right - 1, bottom - 1))  # "\\"
                cv2.line(canvas, *ends, 1, max(1, px(hole.stroke_mm, scene.dpi)))
            image[canvas > 0] = tone
        else:
            image[top:bottom, left:right] = tone
    return replace(scene, image=image)


def holes_painter(holes: Sequence[Hole], tone: Tone = HOLE_TONE) -> Painter:
    return lambda scene: with_holes(scene, holes, tone)


def with_number(
    scene: Scene, digits: str, *, centre_x_mm: float, y_mm: float, tone: int = INK_TONE
) -> Scene:
    """A page number in seven-segment digits, centred on ``centre_x_mm`` (from the paper's left
    edge) with its top ``y_mm`` from the paper's top."""
    width, height = (px(size, scene.dpi) for size in DIGIT_MM)
    stroke, pitch = px(DIGIT_STROKE_MM, scene.dpi), px(DIGIT_PITCH_MM, scene.dpi)
    total = pitch * (len(digits) - 1) + width
    left = scene.paper_x[0] + px(centre_x_mm, scene.dpi) - total // 2
    top = scene.paper_top + px(y_mm, scene.dpi)
    mid = height // 2 - stroke // 2
    boxes = {  # x0, y0, x1, y1 within the digit's cell
        "a": (0, 0, width, stroke),
        "b": (width - stroke, 0, width, mid + stroke),
        "c": (width - stroke, mid, width, height),
        "d": (0, height - stroke, width, height),
        "e": (0, mid, stroke, height),
        "f": (0, 0, stroke, mid + stroke),
        "g": (0, mid, width, mid + stroke),
    }
    image = scene.image.copy()
    for index, digit in enumerate(digits):
        for segment in SEGMENTS[digit]:
            x0, y0, x1, y1 = boxes[segment]
            x = left + index * pitch
            image[top + y0 : top + y1, x + x0 : x + x1] = tone
    return replace(scene, image=image)


def _off_by(scene: Scene, shift_mm: tuple[float, float], tilt_deg: float) -> Scene:
    """The scene moved ``shift_mm`` right and down and turned ``tilt_deg`` about its centre."""
    if shift_mm == (0.0, 0.0) and tilt_deg == 0.0:
        return scene
    height, width = scene.image.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), tilt_deg, 1.0)
    matrix[:, 2] += (px(shift_mm[0], scene.dpi), px(shift_mm[1], scene.dpi))
    moved = cv2.warpAffine(
        scene.image,
        matrix,
        (width, height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE,
    )
    return replace(scene, image=moved)


def sheet(  # noqa: PLR0913
    dpi: int,
    front: Sequence[Painter] = (),
    back: Sequence[Painter] = (),
    *,
    paper_mm: tuple[float, float] = SMALL_MM,
    frame_extra_mm: float = 0.0,
    gap_mm: float = 0.0,
    shift_mm: tuple[float, float] = (0.0, 0.0),
    tilt_deg: float = 0.0,
    seed: int = 0,
) -> tuple[Scene, Scene]:
    """The front and the back of one sheet, as the scanner delivers them (JPEG).

    The frame is ``frame_extra_mm`` wider than the paper, which lies ``gap_mm`` from the front's
    left edge; the back sees the sheet flipped, so its paper lies ``gap_mm`` from its RIGHT edge.
    The back is moved ``shift_mm`` and turned ``tilt_deg`` against the front.
    """
    scan = (paper_mm[0] + frame_extra_mm, paper_mm[1])
    sides = []
    for number, (painters, offset) in enumerate(((front, gap_mm), (back, frame_extra_mm - gap_mm))):
        scene = paper_scene(
            dpi=dpi, paper_mm=paper_mm, scan_mm=scan, offset_mm=offset, seed=seed + number
        )
        for painter in painters:
            scene = painter(scene)
        sides.append(scene)
    sides[1] = _off_by(sides[1], shift_mm, tilt_deg)
    return with_jpeg(sides[0]), with_jpeg(sides[1])


def letter_sheet(dpi: int, front: Sequence[Painter] = (), back: Sequence[Painter] = (), **kwargs):
    """A Letter-sized sheet (the staple holes of a real stack lie in its top corners)."""
    return sheet(dpi, front, back, paper_mm=LETTER_MM, **kwargs)
