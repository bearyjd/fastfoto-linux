"""Faint writing, dust on creases and soft creases for the blank-page tests.

Pencil, a thin-pen flat cursive word, a signature wave, hairline stems and a "7" are the faint
things that must not be taken for a fold crease (a stem or a roman "ii" on its own may be); dust is
put ON the creases, where it joins them into one mark; ``softened`` turns any scene into a scan
that is not crisp. Every function returns a
new scene and leaves the one it is given unchanged.
"""

import math
from dataclasses import replace

import cv2
import numpy as np
from PIL import ImageDraw

from tests.doc_synth import MM_PER_INCH, SPECK_TONE, Scene, _draw, px
from tests.doc_synth_creases import CREASE_SHARES, _paper_size_mm

CURSIVE_PITCH_MM = 2.4  # one loop of the word every 2.4 mm
CURSIVE_HEIGHT_MM = 2.6
CURSIVE_LOOP_MM = 0.85  # how far each loop reaches back: a flat garland of loops
CURSIVE_STROKE_MM = 0.35
WAVE_STROKE_MM = 0.5
WAVE_PERIOD_MM = 21.0
SAMPLES_PER_CYCLE = 40
GRAIN_SAMPLES = 1  # a fleck is one step of the stroke, about 0.16 mm ...
GRAIN_PERIOD_SAMPLES = 6  # ... in every sixth step, about 1 mm
DUST_GAP_MM = 4.0  # specks on a crease are this far apart: two never join into a letter
DUST_COLUMN_TONE = 200  # a column holds crease where the row is darker than this
DUST_DARK_TONE = 120  # darker than any crease: a speck already there
SHADOW_SIGMA_MM = 4.0
SHADOW_LEVELS = 12  # soft shadow beside a fold; a mark needs at least 45
TINT = (0, 3, 8)  # grey levels taken off red, green and blue: a warm sheet


def _stroke(scene: Scene, points: list[tuple[float, float]], tone: int, width_mm: float) -> Scene:
    stroke = max(1, px(width_mm, scene.dpi))

    def paint(draw: ImageDraw.ImageDraw) -> None:
        draw.line(points, fill=(tone, tone, tone), width=stroke, joint="curve")

    return replace(scene, image=_draw(scene, paint))


def with_cursive_word(  # noqa: PLR0913
    scene: Scene,
    x_mm: float,
    y_mm: float,
    *,
    tone: int,
    cycles: int = 10,
    grain_tone: int | None = None,
    stroke_mm: float = CURSIVE_STROKE_MM,
) -> Scene:
    """A flat cursive word of ``cycles`` loops (about 25 x 2.6 mm for ten) in one grey level.

    (``x_mm``, ``y_mm``) is the top left, measured from the paper's top left. With ``grain_tone``
    0.16 mm in every millimetre of the stroke is that darker grey: flecks of pencil, the grain of
    the line.
    """
    left = scene.paper_x[0] + px(x_mm, scene.dpi)
    scale = scene.dpi / MM_PER_INCH
    points = []
    for step in range(cycles * SAMPLES_PER_CYCLE + 1):
        angle = 2 * math.pi * step / SAMPLES_PER_CYCLE
        x_mm_now = CURSIVE_PITCH_MM * angle / (2 * math.pi) - CURSIVE_LOOP_MM * math.sin(angle)
        y_mm_now = CURSIVE_HEIGHT_MM / 2 * (1 - math.cos(angle))
        points.append((left + x_mm_now * scale, px(y_mm, scene.dpi) + y_mm_now * scale))
    word = _stroke(scene, points, tone, stroke_mm)
    if grain_tone is None:
        return word
    for start in range(0, len(points) - GRAIN_SAMPLES, GRAIN_PERIOD_SAMPLES):
        word = _stroke(word, points[start : start + GRAIN_SAMPLES + 1], grain_tone, stroke_mm)
    return word


def with_wave(  # noqa: PLR0913
    scene: Scene,
    x_mm: float,
    y_mm: float,
    *,
    tone: int,
    length_mm: float,
    amplitude_mm: float,
    stroke_mm: float = WAVE_STROKE_MM,
) -> Scene:
    """A flat signature wave: a thin stroke (0.5 mm wide) swinging up and down ``amplitude_mm``
    about the line through (``x_mm``, ``y_mm``)."""
    left = scene.paper_x[0] + px(x_mm, scene.dpi)
    scale = scene.dpi / MM_PER_INCH
    count = max(2, round(length_mm / WAVE_PERIOD_MM * SAMPLES_PER_CYCLE * 4))
    points = []
    for step in range(count + 1):
        along = length_mm * step / count
        swing = amplitude_mm * math.sin(2 * math.pi * along / WAVE_PERIOD_MM)
        points.append((left + along * scale, px(y_mm, scene.dpi) + swing * scale))
    return _stroke(scene, points, tone, stroke_mm)


def _paper_points(scene: Scene, points_mm: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Points measured from the paper's top left, in image pixels."""
    return [(scene.paper_x[0] + px(x, scene.dpi), px(y, scene.dpi)) for x, y in points_mm]


def with_stem(  # noqa: PLR0913
    scene: Scene, x_mm: float, y0_mm: float, y1_mm: float, *, tone: int, stroke_mm: float
) -> Scene:
    """A hairline stem: one vertical stroke from ``y0_mm`` to ``y1_mm`` (an "l", a "1")."""
    points = _paper_points(scene, [(x_mm, y0_mm), (x_mm, y1_mm)])
    return _stroke(scene, points, tone, stroke_mm)


def with_seven(  # noqa: PLR0913
    scene: Scene, x_mm: float, y_mm: float, size_mm: float, *, tone: int, stroke_mm: float
) -> Scene:
    """A "7": a bar ``size_mm`` wide from (``x_mm``, ``y_mm``) and a diagonal 1.4 times as long."""
    corner = (x_mm + size_mm, y_mm)
    foot = (x_mm + size_mm * 0.3, y_mm + size_mm * 1.4)
    points = _paper_points(scene, [(x_mm, y_mm), corner, foot])
    return _stroke(scene, points, tone, stroke_mm)


def with_roman_two(
    scene: Scene, x_mm: float, y_mm: float, *, tone: int, joined: bool = False
) -> Scene:
    """A roman page number "ii" in a faint thin pen: two stems 2.6 mm tall and 1.2 mm apart, which
    are ``joined`` by a stroke along the foot when written in cursive."""
    stroke = CURSIVE_STROKE_MM
    top, foot, right = y_mm, y_mm + CURSIVE_HEIGHT_MM, x_mm + 1.2
    left = with_stem(scene, x_mm, top, foot, tone=tone, stroke_mm=stroke)
    both = with_stem(left, right, top, foot, tone=tone, stroke_mm=stroke)
    if not joined:
        return both
    link = _paper_points(both, [(x_mm, foot), (right, foot)])
    return _stroke(both, link, tone, stroke)


def with_zigzag(  # noqa: PLR0913
    scene: Scene,
    x_mm: float,
    y_mm: float,
    length_mm: float,
    *,
    tone: int,
    swing_mm: float,
    tooth_mm: float,
    stroke_mm: float,
) -> Scene:
    """A scribble-out: a stroke ``stroke_mm`` wide zigzagging ``swing_mm`` either side of a line
    through (``x_mm``, ``y_mm``), a tooth every ``tooth_mm``."""
    count = round(length_mm / tooth_mm)
    points = [
        (x_mm + length_mm * step / count, y_mm + swing_mm * (1 if step % 2 else -1))
        for step in range(count + 1)
    ]
    return _stroke(scene, _paper_points(scene, points), tone, stroke_mm)


def with_bowed_line(  # noqa: PLR0913
    scene: Scene,
    x_mm: float,
    top_mm: float,
    length_mm: float,
    bow_mm: float,
    *,
    tone: int,
    stroke_mm: float,
) -> Scene:
    """A line ``length_mm`` tall whose middle is ``bow_mm`` off the chord between its ends."""
    steps = 60
    points = [
        (x_mm + bow_mm * (1 - (2 * step / steps - 1) ** 2), top_mm + length_mm * step / steps)
        for step in range(steps + 1)
    ]
    return _stroke(scene, _paper_points(scene, points), tone, stroke_mm)


def with_dust_on_creases(
    creased: Scene, count: int, *, max_mm: float = 0.9, tone: int = SPECK_TONE, seed: int = 1
) -> Scene:
    """Up to ``count`` dark specks of 1 pixel to ``max_mm`` sitting ON the horizontal creases of
    ``creased`` (``with_creases``), each over a column where the crease is, half way up or down
    its width: every one joins its crease into one mark. Specks stay ``DUST_GAP_MM`` apart, and
    clear of any dark speck that is already there (two that touch are one speck of letter size)."""
    rng = np.random.default_rng(seed)
    image = creased.image.copy()
    height_mm = _paper_size_mm(creased)[1]
    rows = [px(height_mm * share, creased.dpi) for share in CREASE_SHARES]
    gap, biggest = px(DUST_GAP_MM, creased.dpi), max(1, px(max_mm, creased.dpi))
    placed: list[tuple[int, int]] = []
    for _ in range(count * 8):
        if len(placed) == count:
            break
        row = rows[int(rng.integers(len(rows)))]
        columns = np.nonzero(creased.image[row].min(axis=1) < DUST_COLUMN_TONE)[0]
        if columns.size == 0:
            continue
        x, size = int(rng.choice(columns)), int(rng.integers(1, biggest + 1))
        if any(abs(x - other) < gap and row == other_row for other, other_row in placed):
            continue
        if creased.image[row - gap : row + gap, max(0, x - gap) : x + gap].min() < DUST_DARK_TONE:
            continue
        placed.append((x, row))
        top = row - int(rng.integers(0, size))
        image[top : top + size, x : x + size] = tone
    return replace(creased, image=image)


def softened(scene: Scene, *, blur_mm: float = 0.08, shadow_levels: int = SHADOW_LEVELS) -> Scene:
    """The scene as a scan that is not crisp: blurred over ``blur_mm``, a warm tint, and a soft
    shadow (``shadow_levels`` deep, 4 mm wide) along the creases' rows."""
    dpi = scene.dpi
    image = scene.image.astype(np.float32)
    sigma = blur_mm * dpi / MM_PER_INCH
    if sigma > 0:
        image = cv2.GaussianBlur(image, (0, 0), sigma)
    rows_mm = np.arange(image.shape[0]) * MM_PER_INCH / dpi
    height_mm = _paper_size_mm(scene)[1]
    shadow = np.zeros_like(rows_mm)
    for share in CREASE_SHARES:
        shadow += np.exp(-0.5 * ((rows_mm - height_mm * share) / SHADOW_SIGMA_MM) ** 2)
    shadow = np.where(rows_mm < height_mm, shadow * shadow_levels, 0.0).astype(np.float32)
    image = image - shadow[:, None, None] - np.asarray(TINT, np.float32)
    return replace(scene, image=np.clip(np.rint(image), 0, 255).astype(np.uint8))
