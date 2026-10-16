"""Synthetic scanned pages for the documents tests: paper, text-like marks, specks, backing, tail.

No fonts are needed: a "character" is a small glyph made of strokes, so a line of text is a row of
separate marks the size of real letters. Everything is seeded and drawn at the resolution a test
asks for (100 dpi keeps a Letter page under a megapixel). Functions return new scenes and never
change the one they are given.
"""

from dataclasses import dataclass, replace
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

from fastfoto_linux.pipeline.crop import BACKGROUND_PRIOR_RGB

MM_PER_INCH = 25.4
LETTER_MM = (215.9, 279.4)
LEGAL_MM = (215.9, 355.6)
PAPER_TONE = 240
TAIL_TONE = 255
INK_TONE = 30
PENCIL_TONE = 150
LIGHT_PENCIL_TONE = 180  # 60 grey levels darker than the paper
SPECK_TONE = 70
# The blue-grey strip beside a narrow item: the colour measured on real scans, which the photo
# cropper also uses (a printed sidebar of any other blue-grey is not backing).
BACKING_RGB = (
    round(BACKGROUND_PRIOR_RGB[0]),
    round(BACKGROUND_PRIOR_RGB[1]),
    round(BACKGROUND_PRIOR_RGB[2]),
)
GLYPH_HEIGHT_MM = 2.5
STROKE_MM = 0.4
MIN_STROKE_PX = 2

Box = tuple[int, int, int, int]  # x0, y0, x1, y1 in pixels, end exclusive


def px(mm: float, dpi: int) -> int:
    return round(mm * dpi / MM_PER_INCH)


@dataclass(frozen=True)
class Scene:
    """What the scanner delivered, and where the paper and the ink are in it."""

    image: np.ndarray  # RGB uint8
    dpi: int
    content: Box | None  # box around everything inked (None: nothing)
    paper_end: int  # first row below the paper (the height when there is no tail)
    paper_x: tuple[int, int]  # first column of the paper, and the first one after it
    paper_top: int = 0  # first row of the paper; positions in mm are measured from here

    @property
    def height(self) -> int:
        return self.image.shape[0]

    @property
    def width(self) -> int:
        return self.image.shape[1]


def paper_scene(  # noqa: PLR0913
    *,
    dpi: int = 100,
    paper_mm: tuple[float, float] = LETTER_MM,
    scan_mm: tuple[float, float] | None = None,
    offset_mm: float = 0.0,
    seed: int = 0,
    noise: int = 2,
    paper_tone: int = PAPER_TONE,
    tail_tone: int | None = TAIL_TONE,
    backing: tuple[int, int, int] = BACKING_RGB,
) -> Scene:
    """A sheet of paper in a scan area at least as big as the sheet.

    The scan area is the paper by default. Where it is wider, the columns beside the paper are
    ``backing``; where it is longer, the rows below the paper are ``tail_tone`` (the same tone as
    the paper when ``tail_tone`` is None). ``noise`` is the paper texture (+-grey levels).
    """
    paper_w, paper_h = px(paper_mm[0], dpi), px(paper_mm[1], dpi)
    scan_w, scan_h = (
        (paper_w, paper_h) if scan_mm is None else (px(scan_mm[0], dpi), px(scan_mm[1], dpi))
    )
    x0 = px(offset_mm, dpi) if offset_mm else 0
    x1 = min(x0 + paper_w, scan_w)  # rounding may overshoot by a pixel
    paper_w = x1 - x0
    assert paper_h <= scan_h, "the paper must fit the scan area"
    rng = np.random.default_rng(seed)
    image = np.empty((scan_h, scan_w, 3), np.uint8)
    image[:] = backing
    image[:, x0:x1] = paper_tone if tail_tone is None else tail_tone
    texture = rng.integers(-noise, noise + 1, (paper_h, paper_w, 1))
    image[:paper_h, x0:x1] = np.clip(paper_tone + texture, 0, 255).astype(np.uint8)
    return Scene(image, dpi, None, paper_h, (x0, x1))


def _union(box: Box | None, other: Box) -> Box:
    if box is None:
        return other
    return (
        min(box[0], other[0]),
        min(box[1], other[1]),
        max(box[2], other[2]),
        max(box[3], other[3]),
    )


def _draw(scene: Scene, paint) -> np.ndarray:
    canvas = Image.fromarray(scene.image)
    paint(ImageDraw.Draw(canvas))
    return np.asarray(canvas).copy()


def with_text(  # noqa: PLR0913
    scene: Scene,
    x_mm: float,
    y_mm: float,
    chars: int,
    *,
    height_mm: float = GLYPH_HEIGHT_MM,
    tone: int = INK_TONE,
) -> Scene:
    """A line of ``chars`` separate glyphs; (x_mm, y_mm) is measured from the paper's top left."""
    dpi = scene.dpi
    height, width = px(height_mm, dpi), px(height_mm * 0.6, dpi)
    stroke = max(MIN_STROKE_PX, px(STROKE_MM, dpi))
    advance = width + 2 * stroke
    left, top = scene.paper_x[0] + px(x_mm, dpi), scene.paper_top + px(y_mm, dpi)
    fill = (tone, tone, tone)

    def paint(draw: ImageDraw.ImageDraw) -> None:
        for index in range(chars):
            x = left + index * advance
            draw.rectangle([x, top, x + stroke - 1, top + height - 1], fill=fill)  # stem
            draw.rectangle([x, top, x + width - 1, top + stroke - 1], fill=fill)  # top bar
            if index % 2:
                mid = top + height // 2
                draw.rectangle([x, mid, x + width - 1, mid + stroke - 1], fill=fill)
            if index % 3 == 0:
                draw.rectangle(
                    [x + width - stroke, top, x + width - 1, top + height - 1], fill=fill
                )

    box = (left, top, left + (chars - 1) * advance + width, top + height)
    return replace(scene, image=_draw(scene, paint), content=_union(scene.content, box))


def with_signature(  # noqa: PLR0913
    scene: Scene,
    x_mm: float,
    y_mm: float,
    *,
    width_mm: float = 40.0,
    height_mm: float = 12.0,
    tone: int = INK_TONE,
) -> Scene:
    """One long connected pen stroke: a single mark far bigger than a letter."""
    dpi = scene.dpi
    left, top = scene.paper_x[0] + px(x_mm, dpi), scene.paper_top + px(y_mm, dpi)
    width, height = px(width_mm, dpi), px(height_mm, dpi)
    stroke = max(MIN_STROKE_PX, px(STROKE_MM, dpi))
    xs = np.linspace(0, width - 1, 60)
    ys = (height / 2) + (height / 2 - stroke) * np.sin(xs / width * 14.0)
    points = [(left + float(x), top + float(y)) for x, y in zip(xs, ys, strict=True)]

    def paint(draw: ImageDraw.ImageDraw) -> None:
        draw.line(points, fill=(tone, tone, tone), width=stroke)

    box = (left, top, left + width, top + height)
    return replace(scene, image=_draw(scene, paint), content=_union(scene.content, box))


def with_specks(scene: Scene, count: int, *, seed: int = 1, max_px: int = 3) -> Scene:
    """Dust: up to ``count`` dark squares of 1 to ``max_px`` pixels on the paper (not content).

    Specks keep a gap between them, so two never join into something letter-sized.
    """
    rng = np.random.default_rng(seed)
    image = scene.image.copy()
    spacing = 2 * max_px + 4
    placed: list[tuple[int, int]] = []
    for _ in range(count * 4):
        if len(placed) == count:
            break
        size = int(rng.integers(1, max_px + 1))
        y = int(rng.integers(0, scene.paper_end - size))
        x = int(rng.integers(scene.paper_x[0], scene.paper_x[1] - size))
        if any(abs(x - px_) < spacing and abs(y - py) < spacing for px_, py in placed):
            continue
        placed.append((x, y))
        image[y : y + size, x : x + size] = SPECK_TONE
    return replace(scene, image=image)


def with_show_through(scene: Scene, source: Scene, *, peak: int = 30) -> Scene:
    """Faint, blurred, mirrored ink of ``source`` (the other side of the sheet) in the paper."""
    darkness = np.clip(PAPER_TONE - source.image.min(axis=2).astype(np.float32), 0, None)
    ghost = cv2.GaussianBlur(np.fliplr(darkness), (0, 0), px(1.2, scene.dpi))
    if ghost.max() > 0:
        ghost *= peak / ghost.max()
    height, width = scene.paper_end, scene.paper_x[1] - scene.paper_x[0]
    region = np.zeros(scene.image.shape[:2], np.float32)
    region[:height, scene.paper_x[0] : scene.paper_x[1]] = ghost[:height, :width]
    image = np.clip(scene.image.astype(np.float32) - region[..., None], 0, 255)
    return replace(scene, image=image.astype(np.uint8))


def with_solid_block(scene: Scene, x_mm: float, y_mm: float, size_mm: float, tone: int) -> Scene:
    """A filled square (a stamp, a logo), counted as content."""
    left, top, side = (
        scene.paper_x[0] + px(x_mm, scene.dpi),
        scene.paper_top + px(y_mm, scene.dpi),
        px(size_mm, scene.dpi),
    )
    image = scene.image.copy()
    image[top : top + side, left : left + side] = tone
    return replace(
        scene, image=image, content=_union(scene.content, (left, top, left + side, top + side))
    )


def with_tinted_block(
    scene: Scene, x_mm: float, y_mm: float, size_mm: tuple[float, float], rgb: tuple[int, int, int]
) -> Scene:
    """A filled rectangle of one colour that is not counted as content (a form's coloured bar)."""
    left, top = scene.paper_x[0] + px(x_mm, scene.dpi), scene.paper_top + px(y_mm, scene.dpi)
    width, height = px(size_mm[0], scene.dpi), px(size_mm[1], scene.dpi)
    image = scene.image.copy()
    image[top : top + height, left : left + width] = rgb
    return replace(scene, image=image)


def with_full_width_tail(scene: Scene, tone: int = TAIL_TONE) -> Scene:
    """The rows below the paper in ``tone`` across the whole width, backing columns included."""
    image = scene.image.copy()
    image[scene.paper_end :] = tone
    return replace(scene, image=image)


def to_grey(image: np.ndarray) -> np.ndarray:
    return np.asarray(Image.fromarray(image).convert("L")).copy()


def to_bilevel(image: np.ndarray) -> np.ndarray:
    """A 1-bit page as the loader gives it: uint8 holding only 0 and 255."""
    return np.where(to_grey(image) >= 128, 255, 0).astype(np.uint8)


def write_png(
    path: Path, pixels: np.ndarray, *, dpi: int | None = 100, mode: str | None = None
) -> Path:
    """Save ``pixels`` as a PNG: RGB for ``HxWx3``, 8-bit grey for ``HxW`` uint8 (``mode="1"``
    writes a 1-bit PNG from a 0/255 array), with ``dpi`` unless it is None."""
    picture = Image.fromarray(pixels >= 128) if mode == "1" else Image.fromarray(pixels)
    extra = {} if dpi is None else {"dpi": (dpi, dpi)}
    picture.save(path, "PNG", **extra)
    return path


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
    return np.where(pad[..., None], 255, _noisy(rng, BACKING_RGB, rows, width)).astype(np.uint8)


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
