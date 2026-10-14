"""Synthetic FF-680W ADF frames for tests (test helper, not package code).

Mimics the measured layout of real raw frames: light blue-grey scanner background with noise, a
thin near-white strip on one side edge, the photo near the top, a grey band under the paper and a
pure-white tail. ``make_frame`` also returns the exact box the photo was painted into so tests can
check a cropper against ground truth. Optional knobs reproduce harder real-world cases: no grey
band, rolled-off edges, a soft shadow around the print, pale or cream paper, sky-coloured areas.
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
FLAT_PHOTO_NOISE_STD = 4.0
SKY_RGB = (190, 203, 222)  # a front area that is almost the scanner background colour
HALO_SHIFT = 17  # per-channel darkening of the shadow ring: about 29 RGB units from the background


def _paint_flat(
    canvas: np.ndarray, box: Box, rgb: tuple[int, int, int], rng: np.random.Generator
) -> None:
    noise = rng.normal(0, FLAT_PHOTO_NOISE_STD, size=(box.h, box.w, 3))
    photo = np.clip(np.asarray(rgb) + noise, 0, 255).astype(np.uint8)
    canvas[box.y : box.y + box.h, box.x : box.x + box.w] = photo


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


def _paint_back(
    canvas: np.ndarray,
    box: Box,
    rng: np.random.Generator,
    rgb: tuple[int, int, int] | None,
    noise_std: float,
) -> None:
    base = np.asarray(rgb if rgb else (PAPER_GREY,) * 3, dtype=np.float32)
    paper = base + rng.normal(0, noise_std, size=(box.h, box.w, 1))
    canvas[box.y : box.y + box.h, box.x : box.x + box.w] = np.clip(paper, 0, 255).astype(np.uint8)


def _paint_sky(
    canvas: np.ndarray, box: Box, dpi: int, sky_mm: float, rng: np.random.Generator
) -> None:
    """Replace the top ``sky_mm`` of a front photo with a nearly background-coloured area."""
    rows = min(box.h, mm_to_px(sky_mm, dpi))
    sky = SKY_RGB + rng.normal(0, BACKGROUND_NOISE_STD, size=(rows, box.w, 3))
    canvas[box.y : box.y + rows, box.x : box.x + box.w] = np.clip(sky, 0, 255).astype(np.uint8)


def _paint_halo(canvas: np.ndarray, box: Box, dpi: int, halo_mm: float) -> None:
    """Darken a ring around the photo, like the soft shadow real prints cast on the platen."""
    pad = mm_to_px(halo_mm, dpi)
    y0, x0 = max(0, box.y - pad), max(0, box.x - pad)
    window = canvas[y0 : box.y + box.h + pad, x0 : box.x + box.w + pad]
    ring = np.ones(window.shape[:2], dtype=bool)
    ring[box.y - y0 : box.y - y0 + box.h, box.x - x0 : box.x - x0 + box.w] = False
    window[ring] = np.clip(window[ring].astype(np.int16) - HALO_SHIFT, 0, 255).astype(np.uint8)


def _roll_off_edges(canvas: np.ndarray, behind: np.ndarray, box: Box, blur_px: float) -> None:
    """Fade the photo into what was behind it over ``blur_px`` just inside every edge."""
    ys, xs = np.arange(box.h) + 0.5, np.arange(box.w) + 0.5
    ramp_y = np.clip(np.minimum(ys, box.h - ys) / blur_px, 0, 1)
    ramp_x = np.clip(np.minimum(xs, box.w - xs) / blur_px, 0, 1)
    alpha = np.minimum(ramp_y[:, None], ramp_x[None, :])[:, :, None]
    rows, cols = slice(box.y, box.y + box.h), slice(box.x, box.x + box.w)
    mixed = alpha * canvas[rows, cols] + (1 - alpha) * behind[rows, cols]
    canvas[rows, cols] = np.rint(mixed).astype(np.uint8)


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


def _background(
    shape: tuple[int, int], rng: np.random.Generator, rgb: tuple[int, int, int]
) -> np.ndarray:
    noise = rng.standard_normal((*shape, 3), dtype=np.float32) * BACKGROUND_NOISE_STD
    canvas = np.clip(np.rint(np.asarray(rgb, dtype=np.float32) + noise), 0, 255)
    return canvas.astype(np.uint8)


def _paint_photo(  # noqa: PLR0913
    canvas: np.ndarray,
    box: Box,
    dpi: int,
    rng: np.random.Generator,
    *,
    side: Side,
    photo_rgb: tuple[int, int, int] | None,
    sky_mm: float,
    paper_noise_std: float,
    imprint: bool,
    writing: bool,
) -> None:
    if side == "front":
        if photo_rgb:
            _paint_flat(canvas, box, photo_rgb, rng)
        else:
            _paint_front(canvas, box, dpi, rng)
        if sky_mm:
            _paint_sky(canvas, box, dpi, sky_mm, rng)
        return
    _paint_back(canvas, box, rng, photo_rgb, paper_noise_std)
    if imprint:
        _paint_imprint(canvas, box, dpi, rng)
    if writing:
        _paint_writing(canvas, box, dpi, rng)


def _layout(  # noqa: PLR0913
    dpi: int,
    *,
    photo_mm: tuple[float, float],
    offset_mm: tuple[float, float],
    right_margin_mm: float,
    grey_band_mm: float,
    tail_mm: float,
) -> tuple[Box, int, int, int]:
    """Photo box, first tail row, frame width and frame height, all in pixels."""
    x0, y0 = mm_to_px(offset_mm[0], dpi), mm_to_px(offset_mm[1], dpi)
    x1, y1 = mm_to_px(offset_mm[0] + photo_mm[0], dpi), mm_to_px(offset_mm[1] + photo_mm[1], dpi)
    tail_y = y1 + mm_to_px(grey_band_mm, dpi)
    width, height = x1 + mm_to_px(right_margin_mm, dpi), tail_y + mm_to_px(tail_mm, dpi)
    return Box(x0, y0, x1 - x0, y1 - y0), tail_y, width, height


def _paint_strip(rows: np.ndarray, side: Strip, strip: int, height: int) -> None:
    """Paint the near-white edge strip into the first ``height`` rows of ``rows``."""
    if side == "left":
        rows[:height, :strip] = STRIP_GREY
    elif side == "right":
        rows[:height, rows.shape[1] - strip :] = STRIP_GREY


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
    grey_band_mm: float = GREY_BAND_MM,
    tail_grey: int = TAIL_GREY,
    photo_rgb: tuple[int, int, int] | None = None,
    sky_mm: float = 0.0,
    halo_mm: float = 0.0,
    edge_blur_mm: float = 0.0,
    paper_noise_std: float = PAPER_NOISE_STD,
    strip_through_tail: bool = False,
    background_rgb: tuple[int, int, int] = BACKGROUND_RGB,
) -> tuple[np.ndarray, Box]:
    """Build one synthetic frame and the ground-truth photo ``Box`` (pixels at ``dpi``).

    ``photo_mm`` is ``(width, height)`` and ``offset_mm`` the photo's ``(x, y)`` from the frame's
    top-left. The frame is as wide as ``offset + photo + right_margin_mm`` and as tall as the
    photo, ``grey_band_mm`` of background and ``tail_mm`` of ``tail_grey``. ``imprint`` and
    ``writing`` only affect backs; ``sky_mm`` only fronts. ``photo_rgb`` replaces the photo with a
    flat colour (cream paper on a back, a pale print on a front). ``halo_mm`` adds a soft shadow
    ring around the print and ``edge_blur_mm`` rolls the photo edge off over that distance
    inside the box. ``paper_noise_std`` sets the grain of back paper (0 gives perfectly flat
    paper). ``strip_through_tail`` lets the near-white edge strip run on through the white tail.
    ``background_rgb`` overrides the scanner background colour.
    Everything random derives from ``rng_seed``.
    """
    _validate(photo_mm, offset_mm, side, white_strip)
    rng = np.random.default_rng(rng_seed)
    box, tail_y, width, height = _layout(
        dpi,
        photo_mm=photo_mm,
        offset_mm=offset_mm,
        right_margin_mm=right_margin_mm,
        grey_band_mm=grey_band_mm,
        tail_mm=tail_mm,
    )
    canvas = _background((height, width), rng, background_rgb)
    if halo_mm:
        _paint_halo(canvas, box, dpi, halo_mm)
    strip = max(1, mm_to_px(STRIP_MM, dpi))
    _paint_strip(canvas, white_strip, strip, tail_y)
    behind = canvas.copy() if edge_blur_mm else canvas
    _paint_photo(
        canvas,
        box,
        dpi,
        rng,
        side=side,
        photo_rgb=photo_rgb,
        sky_mm=sky_mm,
        paper_noise_std=paper_noise_std,
        imprint=imprint,
        writing=writing,
    )
    if edge_blur_mm:
        _roll_off_edges(canvas, behind, box, max(1.0, edge_blur_mm * dpi / 25.4))
    canvas[tail_y:] = tail_grey
    if strip_through_tail:
        _paint_strip(canvas[tail_y:], white_strip, strip, height - tail_y)
    return canvas, box
