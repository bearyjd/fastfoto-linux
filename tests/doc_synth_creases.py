"""Synthetic fold creases, rules and pencil handwriting for the blank-page tests.

The numbers come from the creased blank backs of real letters: creases 0.17-0.51 mm thick, darkest
pixel 152-204, in segments 2-23 mm long, two rows at a third and two thirds of the page; a faint
tall artefact 7.6 x 153 mm along a deskewed edge, darkest 176. Pencil is darkest 110-150 with
letters 2-3 mm tall. Every function returns a new scene and leaves the one it is given unchanged.
"""

from dataclasses import replace

import numpy as np
from PIL import ImageDraw

from tests.doc_synth import MM_PER_INCH, Scene, _draw, px, with_specks

CREASE_TONE = 175
CREASE_MM = 0.3
CREASE_SEGMENT_MM = (2.0, 23.0)
CREASE_GAP_MM = (3.0, 15.0)  # gaps stay wider than two pixels at 150 dpi: pieces never join
CREASE_SHARES = (1 / 3, 2 / 3)
DUST_CLEARANCE_MM = 2.0
ARTEFACT_TONE = 176
ARTEFACT_BOX_MM = (7.6, 153.0)
ARTEFACT_THICKNESS_MM = 0.4
PENCIL_TONES = (110, 130, 150, 140, 120)
PENCIL_HEIGHT_MM = 2.6
PENCIL_STROKE_MM = 0.35
PENCIL_WIDTH_SHARE = 0.65  # the width of a letter, as a share of its height
PENCIL_ADVANCE_MM = 2.4
WORD_SPACE_MM = 2.4

Point = tuple[float, float]
# A letter is a list of strokes; a stroke is a polyline in a unit box (x right, y down).
_RING = [(0.0, 0.5), (0.15, 0.2), (0.5, 0.1), (0.85, 0.2), (1.0, 0.5), (0.85, 0.85), (0.5, 0.95)]
_LETTERS: dict[str, list[list[Point]]] = {
    "o": [[*_RING, (0.15, 0.85), (0.0, 0.5)]],
    "a": [[*_RING, (0.15, 0.85), (0.0, 0.5)], [(1.0, 0.1), (1.0, 1.0)]],
    "l": [[(0.5, 0.0), (0.5, 1.0)]],
    "t": [[(0.5, 0.0), (0.5, 1.0)], [(0.1, 0.35), (0.9, 0.35)]],
    "n": [[(0.0, 1.0), (0.0, 0.3), (0.4, 0.1), (0.8, 0.3), (0.8, 1.0)]],
}


def _paper_size_mm(scene: Scene) -> tuple[float, float]:
    """The paper's width and height in millimetres."""
    width = (scene.paper_x[1] - scene.paper_x[0]) * MM_PER_INCH / scene.dpi
    return width, scene.paper_end * MM_PER_INCH / scene.dpi


def with_line(
    scene: Scene, start_mm: Point, end_mm: Point, *, tone: int, thickness_mm: float
) -> Scene:
    """A straight line in one grey level; the points are measured from the paper's top left.

    A horizontal or vertical line is exact (``thickness_mm`` rounded to whole pixels, at least
    one), so a short one is a bar. It is not counted as content.
    """
    dpi = scene.dpi
    (x0, y0), (x1, y1) = (
        (scene.paper_x[0] + px(x, dpi), px(y, dpi)) for x, y in (start_mm, end_mm)
    )
    width = max(1, px(thickness_mm, dpi))
    fill = (tone, tone, tone)

    def paint(draw: ImageDraw.ImageDraw) -> None:
        if y0 == y1:
            draw.rectangle([x0, y0, x1, y0 + width - 1], fill=fill)
        elif x0 == x1:
            draw.rectangle([x0, y0, x0 + width - 1, y1], fill=fill)
        else:
            draw.line([(x0, y0), (x1, y1)], fill=fill, width=width)

    return replace(scene, image=_draw(scene, paint))


def _segments(
    rng: np.random.Generator, from_mm: float, length_mm: float
) -> list[tuple[float, float]]:
    """Pieces of a crease 2-23 mm long, with gaps, from ``from_mm`` to the far end of the paper."""
    pieces: list[tuple[float, float]] = []
    start = from_mm + float(rng.uniform(0.0, CREASE_GAP_MM[1]))
    while start < length_mm:
        stop = min(length_mm, start + float(rng.uniform(*CREASE_SEGMENT_MM)))
        pieces.append((start, stop))
        start = stop + float(rng.uniform(*CREASE_GAP_MM))
    return pieces


def with_creases(  # noqa: PLR0913
    scene: Scene,
    *,
    tone: int = CREASE_TONE,
    thickness_mm: float = CREASE_MM,
    vertical: bool = False,
    broken: bool = False,
    from_mm: float = 0.0,
    seed: int = 3,
) -> Scene:
    """Two fold creases, at a third and two thirds of the paper's height (width if ``vertical``).

    Each runs from ``from_mm`` to the far side of the paper, or when ``broken`` as separate
    segments 2-23 mm long. Horizontal and vertical creases are not combined in one scene: where
    they cross they would be one mark.
    """
    width, height = _paper_size_mm(scene)
    along, across = (height, width) if vertical else (width, height)
    rng = np.random.default_rng(seed)
    for share in CREASE_SHARES:
        for start, stop in _segments(rng, from_mm, along) if broken else [(from_mm, along)]:
            ends = (
                ((across * share, start), (across * share, stop))
                if vertical
                else (
                    (start, across * share),
                    (stop, across * share),
                )
            )
            scene = with_line(scene, *ends, tone=tone, thickness_mm=thickness_mm)
    return scene


def with_dust_clear_of_creases(
    creased: Scene, count: int, *, max_px: int = 3, seed: int = 1
) -> Scene:
    """Dust on a scene with horizontal creases, none of it within 2 mm of a crease: a speck that
    touches a crease would join it into one mark that is not faint."""
    dusty = with_specks(creased, count, max_px=max_px, seed=seed)
    rows = np.arange(creased.image.shape[0]) * MM_PER_INCH / creased.dpi
    height = _paper_size_mm(creased)[1]
    near = np.zeros(rows.shape, bool)
    for share in CREASE_SHARES:
        near |= np.abs(rows - height * share) < DUST_CLEARANCE_MM
    return replace(dusty, image=np.where(near[:, None, None], creased.image, dusty.image))


def with_slanted_artefact(
    scene: Scene, *, tone: int = ARTEFACT_TONE, x_mm: float = 6.0, top_mm: float = 50.0
) -> Scene:
    """A thin faint line 7.6 mm across and 153 mm tall, 6 mm in from the side: what a deskewed
    scan leaves along the slanted edge of the pad."""
    run, rise = ARTEFACT_BOX_MM
    return with_line(
        scene,
        (x_mm, top_mm),
        (x_mm + run, top_mm + rise),
        tone=tone,
        thickness_mm=ARTEFACT_THICKNESS_MM,
    )


def with_pencil_words(
    scene: Scene,
    x_mm: float,
    y_mm: float,
    words: str = "tall not lot",
    *,
    tones: tuple[int, ...] = PENCIL_TONES,
) -> Scene:
    """Handwriting in pencil: letters of 2.6 mm, strokes of 0.35 mm, the grey level of each letter
    taken in turn from ``tones``. Letters (a l n o t) are separate marks, as printed ones are."""
    dpi = scene.dpi
    height = px(PENCIL_HEIGHT_MM, dpi)
    width = round(height * PENCIL_WIDTH_SHARE)
    stroke = max(1, px(PENCIL_STROKE_MM, dpi))
    advance, space = px(PENCIL_ADVANCE_MM, dpi), px(WORD_SPACE_MM, dpi)
    left, top = scene.paper_x[0] + px(x_mm, dpi), px(y_mm, dpi)

    def paint(draw: ImageDraw.ImageDraw) -> None:
        x = left
        for index, letter in enumerate(words):
            if letter == " ":
                x += space
                continue
            tone = tones[index % len(tones)]
            for line in _LETTERS[letter]:
                points = [(x + ux * width, top + uy * height) for ux, uy in line]
                draw.line(points, fill=(tone, tone, tone), width=stroke, joint="curve")
            x += advance

    return replace(scene, image=_draw(scene, paint))
