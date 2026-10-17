"""Synthetic scanner frames with the backing band, as the real scanner sends them: the band, the
slanted pad and its side wedges, the white tail, rotated by the deskew and sent as JPEG. Built on
the paper scenes of ``doc_synth``; numbers measured on real pages, nothing from a real pixel.
"""

import io
import math
from dataclasses import replace

import cv2
import numpy as np
from PIL import Image

from tests.doc_synth import BACKING_RGB, LETTER_MM, Scene, px

# ---- the scanner's backing band, as measured on real pages (numbers only, no pixels) ----------

SHADOW_RGB = (189, 194, 202)  # backing next to the paper: about 27 from the backing, past 20
PAD_WEDGE_MM = 10.0  # the deskew's pad: its upper boundary is slanted over this much height
PAD_FIRST_ROW_SHARE = 0.95  # the pad covers this much of the bottom row; none of it at the top
EDGE_LINE_MM = 1.0
EDGE_LINE_TONE = 105  # the dark pixels of the paper's edge line (under 120)
EDGE_LINE_SHARE = {"bottom": 0.45, "top": 0.2}  # the share of a row's pixels on the line
TOP_PAD_SHARE = 0.15  # the first row at the top: this much of it is pad, the rest backing
BAND_NOISE = 2


def _noisy(rng: np.random.Generator, rgb: tuple[int, int, int], rows: int, width: int):
    """``rows`` x ``width`` pixels of ``rgb`` with +-``BAND_NOISE`` levels on every channel."""
    noise = rng.integers(-BAND_NOISE, BAND_NOISE + 1, (rows, width, 3))
    return np.clip(np.asarray(rgb) + noise, 0, 255).astype(np.uint8)


def _edge_line(rng: np.random.Generator, rows: int, width: int, share: float, paper: int):
    """A dark edge line of ``rows``: ``share`` of each row's pixels are dark, the rest paper."""
    dark = rng.random((rows, width, 1)) < share
    return np.where(dark, EDGE_LINE_TONE, paper).astype(np.uint8).repeat(3, axis=2)


def _pad_wedge(rng: np.random.Generator, dpi: int, width: int) -> np.ndarray:
    """The rows at the bottom of the frame: pure white pad over a slanted boundary above the
    bottom edge, backing beside it; at the first row the pad is 95% of the width, at the top of
    the wedge nothing is left."""
    rows = px(PAD_WEDGE_MM, dpi)
    above_bottom = (rows - 1 - np.arange(rows))[:, None] * (PAD_WEDGE_MM / rows)
    across = np.arange(width)[None, :] / width
    pad = above_bottom < PAD_WEDGE_MM * (PAD_FIRST_ROW_SHARE - across)
    image = np.where(pad[..., None], 255, _noisy(rng, BACKING_RGB, rows, width)).astype(np.uint8)
    cross = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
    fringe = cv2.dilate(pad.astype(np.uint8), cross).astype(bool) & ~pad
    image[fringe] = (255 + np.asarray(BACKING_RGB)) // 2  # one pixel where the two blend
    return image


def banded_scene(  # noqa: PLR0913
    *,
    dpi: int = 100,
    width_mm: float = LETTER_MM[0],
    paper_mm: float = 60.0,
    band_mm: float = 10.0,
    top_mm: float = 0.0,
    shadow_mm: float = 0.8,
    edge_line: bool = True,
    paper_noise: int = 0,
    seed: int = 0,
) -> Scene:
    """A page as the scanner delivered it with the paper deskewed: from the top, ``top_mm`` of
    backing (the first row part pad), the paper (pure 255, or 254-255 with ``paper_noise``) with
    an edge line of 1 mm on each side that has backing, ``shadow_mm`` of darker backing, the
    full-width ``band_mm`` of backing, and the slanted pad over the bottom edge.

    ``paper_top`` is the first row of the paper including its top edge line, ``paper_end`` the
    first row after the paper including its bottom edge line. ``edge_line`` draws the lines.
    """
    rng = np.random.default_rng(seed)
    width = px(width_mm, dpi)
    line = px(EDGE_LINE_MM, dpi) if edge_line else 0

    def paper_rows(rows: int) -> np.ndarray:
        tone = 255 - rng.integers(0, paper_noise + 1, (rows, width, 1))
        return tone.astype(np.uint8).repeat(3, axis=2)

    parts: list[np.ndarray] = []
    if top_mm:
        top = _noisy(rng, BACKING_RGB, px(top_mm, dpi), width)
        top[0, : round(width * TOP_PAD_SHARE)] = 255
        parts.append(top)
    if line and top_mm:
        parts.append(_edge_line(rng, line, width, EDGE_LINE_SHARE["top"], 255))
    paper_top = sum(part.shape[0] for part in parts) - (line if top_mm else 0)
    parts.append(paper_rows(px(paper_mm, dpi)))
    paper_end = sum(part.shape[0] for part in parts) + line
    if line:
        parts.append(_edge_line(rng, line, width, EDGE_LINE_SHARE["bottom"], 255))
    parts.append(_noisy(rng, SHADOW_RGB, px(shadow_mm, dpi), width))
    parts.append(_noisy(rng, BACKING_RGB, px(band_mm, dpi), width))
    parts.append(_pad_wedge(rng, dpi, width))
    return Scene(np.concatenate(parts), dpi, None, paper_end, (0, width), max(0, paper_top))


# ---- a whole frame as the real scanner sends it: deskewed, a long white tail, JPEG --------------

FRAME_TAIL_MM = 98.0  # white tail of a full frame: 393 mm at 300 dpi under Letter paper
LEVER_MM = 280.0  # from the rotation's pivot to the band: a Letter page long, so 3 degrees move
# the band's rows 14.6 mm sideways (the side wedge of pad)
JPEG_QUALITY = 90


def with_jpeg(scene: Scene) -> Scene:
    """The scene as the scanner sends it: JPEG, quality 90, no chroma subsampling (4:4:4).
    Applied last, after any mark has been drawn, so that every pixel went through the codec."""
    buffer = io.BytesIO()
    Image.fromarray(scene.image).save(buffer, "JPEG", quality=JPEG_QUALITY, subsampling=0)
    buffer.seek(0)
    return replace(scene, image=np.asarray(Image.open(buffer).convert("RGB")).copy())


def _region_alpha(  # noqa: PLR0913, PLR0917
    first_row: int, height: int, width: int, tilt_deg: float, pivot_y: float, end_y: float
) -> np.ndarray:
    """How much of each pixel, from ``first_row`` down, the scanned rectangle covers (0 to 1).

    The rectangle has its sides on columns 0 and ``width`` and its lower edge on row ``end_y``
    before it is rotated by ``tilt_deg`` about (width / 2, ``pivot_y``): the deskew. Outside it
    the frame is pad: a slanted lower edge, and wedges up the sides.
    """
    theta = math.radians(tilt_deg)
    sin, cos = math.sin(theta), math.cos(theta)
    dx = np.arange(width, dtype=np.float32)[None, :] + 0.5 - width / 2
    dy = np.arange(first_row, height, dtype=np.float32)[:, None] + 0.5 - pivot_y
    along = width / 2 + dx * cos + dy * sin  # position across the unrotated rectangle
    down = pivot_y - dx * sin + dy * cos  # and down it
    inside = np.minimum(np.minimum(along, width - along), end_y - down)
    return np.clip(inside + 0.5, 0.0, 1.0)


def scanner_page(  # noqa: PLR0913
    *,
    dpi: int = 100,
    width_mm: float = LETTER_MM[0],
    paper_mm: float = 60.0,
    band_mm: float = 10.0,
    shadow_mm: float = 0.8,
    shadow_rgb: tuple[int, int, int] = SHADOW_RGB,
    edge_line: bool = True,
    paper_tone: int = 255,
    tilt_deg: float = 0.0,
    tail_mm: float = FRAME_TAIL_MM,
    lever_mm: float = LEVER_MM,
    seed: int = 0,
) -> Scene:
    """A full-length frame: the paper axis-aligned (255 like the pad, or ``paper_tone``), an edge
    line, ``shadow_mm`` of darker backing, ``band_mm`` of backing, all below the paper only, then
    ``tail_mm`` of white. The scanned rectangle is rotated by ``tilt_deg`` (the deskew), so the
    pad is everything outside it: a slanted lower edge ``width * tan(tilt)`` high and a wedge up
    one side as wide as ``lever_mm * sin(tilt)`` where the band is. Not JPEG: see ``with_jpeg``.

    ``paper_end`` is the first row after the paper including its bottom edge line.
    """
    rng = np.random.default_rng(seed)
    width = px(width_mm, dpi)
    line = px(EDGE_LINE_MM, dpi) if edge_line else 0
    paper_end = px(paper_mm, dpi) + line
    shadow, band = px(shadow_mm, dpi), px(band_mm, dpi)
    scan_end = paper_end + shadow + band
    drop = math.ceil(width / 2 * math.tan(math.radians(abs(tilt_deg))))  # the lowest corner
    height = scan_end + drop + px(tail_mm, dpi)
    image = np.empty((height, width, 3), np.uint8)
    image[:] = paper_tone
    if line:
        dark = _edge_line(rng, line, width, EDGE_LINE_SHARE["bottom"], paper_tone)
        image[paper_end - line : paper_end] = dark
    scanned = np.concatenate(
        [
            _noisy(rng, shadow_rgb, shadow, width),
            _noisy(rng, BACKING_RGB, height - paper_end - shadow, width),
        ]
    ).astype(np.float32)
    pivot_y = scan_end - px(lever_mm, dpi)
    alpha = _region_alpha(paper_end, height, width, tilt_deg, pivot_y, scan_end)[..., None]
    image[paper_end:] = np.round(alpha * scanned + (1.0 - alpha) * 255.0).astype(np.uint8)
    return Scene(image, dpi, None, paper_end, (0, width))
