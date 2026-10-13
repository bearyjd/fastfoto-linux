"""Synthetic FF-680W ADF frames for tests (test helper, not package code).

Mimics the measured layout of real raw frames: light blue-grey scanner background with noise, a
thin near-white strip on one side edge, the photo near the top, a grey band under the paper and a
pure-white tail. ``make_frame`` also returns the exact box the photo was painted into so tests can
check a cropper against ground truth.
"""

from typing import Literal

import cv2
import numpy as np

from fastfoto_linux.pipeline.crop import Box
from fastfoto_linux.pipeline.geometry import mm_to_px

Side = Literal["front", "back"]
Strip = Literal["left", "right"] | None

BACKGROUND_RGB = (202, 210, 219)
BACKGROUND_NOISE_STD = 3.0
GREY_BAND_MM = 9.0
TAIL_MM = 40.0
RIGHT_MARGIN_MM = 18.0
STRIP_MM = 1.5
STRIP_GREY = 248
TAIL_GREY = 255
PAPER_GREY = 252
PAPER_NOISE_STD = 2.0
IMPRINT_GREY = 200
IMPRINT_DOT_MM = 0.6
IMPRINT_PITCH_MM = 1.4
IMPRINT_LENGTH_MM = 55.0
IMPRINT_INSET_MM = 15.0
WRITING_GREY = 110
WRITING_THICKNESS_MM = 0.5
WRITING_STROKE_MM = (3.0, 7.0)
WRITING_LINES = 2
WRITING_WORDS_PER_LINE = 3
WRITING_STROKES_PER_WORD = (3, 6)
WRITING_WORD_GAP_MM = 8.0
WRITING_STROKE_PITCH_MM = 2.5
WRITING_LINE_PITCH_MM = 11.0
WRITING_INSET_MM = 15.0
FRONT_BLOCK_MM = 6.0
FRONT_GREY_RANGE = (25, 130)


def _paint_front(canvas: np.ndarray, box: Box, dpi: int, rng: np.random.Generator) -> None:
    """Dark-ish textured photo: a colour gradient overlaid with random coarse blocks."""
    h, w = box.h, box.w
    ramp_x = np.linspace(0.0, 1.0, w, dtype=np.float32)[None, :, None]
    ramp_y = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None, None]
    low, high = FRONT_GREY_RANGE
    tint = rng.uniform(0.8, 1.2, size=3).astype(np.float32)
    base = low + (high - low) * (0.5 * ramp_x + 0.5 * ramp_y) * tint
    block = max(1, mm_to_px(FRONT_BLOCK_MM, dpi))
    cells = rng.uniform(-30, 30, size=(h // block + 1, w // block + 1, 3)).astype(np.float32)
    blocks = np.kron(cells, np.ones((block, block, 1), dtype=np.float32))[:h, :w]
    photo = np.clip(base + blocks + rng.normal(0, 4, size=(h, w, 3)), 0, 255)
    canvas[box.y : box.y + h, box.x : box.x + w] = photo.astype(np.uint8)


def _paint_back(canvas: np.ndarray, box: Box, rng: np.random.Generator) -> None:
    paper = rng.normal(PAPER_GREY, PAPER_NOISE_STD, size=(box.h, box.w, 1))
    paper = np.broadcast_to(np.clip(paper, 0, 255), (box.h, box.w, 3))
    canvas[box.y : box.y + box.h, box.x : box.x + box.w] = paper.astype(np.uint8)


def _paint_imprint(canvas: np.ndarray, box: Box, dpi: int, rng: np.random.Generator) -> None:
    """Faint dot-matrix line (the lab/printer imprint on the back of a print)."""
    dot = max(1, mm_to_px(IMPRINT_DOT_MM, dpi))
    pitch = max(dot + 1, mm_to_px(IMPRINT_PITCH_MM, dpi))
    x0 = box.x + mm_to_px(IMPRINT_INSET_MM, dpi)
    y_mid = box.y + box.h // 2
    for x in range(x0, x0 + mm_to_px(IMPRINT_LENGTH_MM, dpi), pitch):
        if x + dot >= box.x + box.w or rng.random() < 0.15:
            continue
        jitter = int(rng.integers(-dot, dot + 1))
        canvas[y_mid + jitter : y_mid + jitter + dot, x : x + dot] = IMPRINT_GREY


def _paint_writing(canvas: np.ndarray, box: Box, dpi: int, rng: np.random.Generator) -> None:
    """Handwriting-like dark zig-zag strokes, several words on two lines."""
    thickness = max(1, mm_to_px(WRITING_THICKNESS_MM, dpi))
    colour = (WRITING_GREY,) * 3
    for line in range(WRITING_LINES):
        baseline = box.y + mm_to_px(WRITING_INSET_MM + (line + 1) * WRITING_LINE_PITCH_MM, dpi)
        x = box.x + mm_to_px(WRITING_INSET_MM, dpi)
        for _word in range(WRITING_WORDS_PER_LINE):
            for _stroke in range(int(rng.integers(*WRITING_STROKES_PER_WORD))):
                height = mm_to_px(float(rng.uniform(*WRITING_STROKE_MM)), dpi)
                lean = int(rng.integers(-height // 3, height // 3 + 1))
                p0, p1 = (x, baseline), (x + lean, baseline - height)
                cv2.line(canvas, p0, p1, colour, thickness, cv2.LINE_AA)
                x += mm_to_px(WRITING_STROKE_PITCH_MM, dpi)
            x += mm_to_px(WRITING_WORD_GAP_MM, dpi)


def _validate(
    photo_mm: tuple[float, float], offset_mm: tuple[float, float], side: str, strip: str | None
) -> None:
    if side not in ("front", "back"):
        raise ValueError(f"side must be 'front' or 'back', got {side!r}")
    if strip not in ("left", "right", None):
        raise ValueError(f"white_strip must be 'left', 'right' or None, got {strip!r}")
    if min(photo_mm) <= 0 or min(offset_mm) < 0:
        raise ValueError("photo_mm must be positive and offset_mm non-negative")


def make_frame(  # noqa: PLR0913
    *,
    dpi: int = 150,
    photo_mm: tuple[float, float] = (178, 127),
    offset_mm: tuple[float, float] = (20, 0.5),
    side: Side = "front",
    writing: bool = False,
    imprint: bool = True,
    white_strip: Strip = "left",
    rng_seed: int = 0,
    right_margin_mm: float = RIGHT_MARGIN_MM,
    tail_mm: float = TAIL_MM,
) -> tuple[np.ndarray, Box]:
    """Build one synthetic frame and the ground-truth photo ``Box`` (pixels at ``dpi``).

    ``photo_mm`` is ``(width, height)`` and ``offset_mm`` the photo's ``(x, y)`` from the frame's
    top-left. The frame is as wide as ``offset + photo + right_margin_mm`` and as tall as the
    photo, a 9 mm grey band and ``tail_mm`` of white. ``imprint`` and ``writing`` only affect
    backs. Everything random derives from ``rng_seed``.
    """
    _validate(photo_mm, offset_mm, side, white_strip)
    rng = np.random.default_rng(rng_seed)
    x0, y0 = mm_to_px(offset_mm[0], dpi), mm_to_px(offset_mm[1], dpi)
    x1, y1 = mm_to_px(offset_mm[0] + photo_mm[0], dpi), mm_to_px(offset_mm[1] + photo_mm[1], dpi)
    box = Box(x0, y0, x1 - x0, y1 - y0)
    tail_y = y1 + mm_to_px(GREY_BAND_MM, dpi)
    width, height = x1 + mm_to_px(right_margin_mm, dpi), tail_y + mm_to_px(tail_mm, dpi)

    noise = rng.standard_normal((height, width, 3), dtype=np.float32) * BACKGROUND_NOISE_STD
    canvas = np.clip(np.rint(np.asarray(BACKGROUND_RGB, dtype=np.float32) + noise), 0, 255)
    canvas = canvas.astype(np.uint8)
    strip = max(1, mm_to_px(STRIP_MM, dpi))
    if white_strip == "left":
        canvas[:tail_y, :strip] = STRIP_GREY
    elif white_strip == "right":
        canvas[:tail_y, width - strip :] = STRIP_GREY
    if side == "front":
        _paint_front(canvas, box, dpi, rng)
    else:
        _paint_back(canvas, box, rng)
        if imprint:
            _paint_imprint(canvas, box, dpi, rng)
        if writing:
            _paint_writing(canvas, box, dpi, rng)
    canvas[tail_y:] = TAIL_GREY
    return canvas, box
