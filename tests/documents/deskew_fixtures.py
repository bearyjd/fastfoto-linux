"""Generated pages for the deskew tests: glyph blobs on rows, seeded, nothing from a scanner.

``skewed`` rotates with OpenCV's own ``getRotationMatrix2D`` and a float angle, never with the
product's ``deskewed``, so a test that undoes it checks the product against an independent
reference. ``skewed(page, t)`` turns the page CLOCKWISE by ``t`` tenths of a degree, so the
tenths that straighten it again are ``-t``.
"""

import cv2
import numpy as np

from fastfoto_linux.documents.loader import LoadedPage
from fastfoto_linux.documents.modes import ColourMode

PAPER = 240
INK = 30
DPI = 300
WIDTH_MM = 150
HEIGHT_MM = 200


def _px(mm: float, dpi: int = DPI) -> int:
    return round(mm * dpi / 25.4)


def blank(dpi: int = DPI) -> np.ndarray:
    return np.full((_px(HEIGHT_MM, dpi), _px(WIDTH_MM, dpi)), PAPER, np.uint8)


def text_page(  # noqa: PLR0913 - the knobs of a fixture
    rng: np.random.Generator,
    *,
    dpi: int = DPI,
    lines: int | None = None,
    width_mm: float = WIDTH_MM,
    height_mm: float = HEIGHT_MM,
    margin_mm: float = 18,
    jitter_mm: float = 0.0,
    mixed: bool = False,
) -> np.ndarray:
    """Rows of glyph blobs (ragged line ends); ``jitter_mm`` moves each glyph off its baseline,
    ``mixed`` gives glyphs different heights."""
    img = np.full((_px(height_mm, dpi), _px(width_mm, dpi)), PAPER, np.uint8)
    height, width = img.shape
    margin, pitch, xh = _px(margin_mm, dpi), _px(6, dpi), _px(2.2, dpi)
    jitter = _px(jitter_mm, dpi) if jitter_mm else 0
    y, drawn = margin, 0
    while y + 2 * xh < height - margin and (lines is None or drawn < lines):
        x = margin
        end = margin + int((width - 2 * margin) * rng.uniform(0.7, 1.0))
        while x < end:
            glyph = _px(rng.uniform(1.2, 2.0), dpi)
            tall = int(xh * rng.uniform(1.0, 1.6)) if mixed else xh
            shift = int(rng.integers(-jitter, jitter + 1)) if jitter else 0
            base = y + xh + shift
            img[base - tall : base, x : x + glyph] = INK
            x += glyph + _px(0.4, dpi) + (_px(1.6, dpi) if rng.random() < 0.17 else 0)
        y += pitch
        drawn += 1
    return img


def hard_page(seed: int) -> np.ndarray:
    """Jittered baselines, mixed heights, a 40x30 mm noise 'photo' block and a ruled table."""
    rng = np.random.default_rng(seed)
    img = text_page(rng, jitter_mm=0.3, mixed=True)
    top, left = _px(120), _px(24)
    noise = rng.integers(60, 230, (_px(30), _px(40)), dtype=np.uint8)
    img[top : top + noise.shape[0], left : left + noise.shape[1]] = noise
    t0, t1, l0 = _px(160), _px(190), _px(24)
    rows, cols, thick = 3, 4, 3
    for i in range(rows + 1):
        y = t0 + (t1 - t0 - thick) * i // rows
        img[y : y + thick, l0 : l0 + _px(80)] = INK
    for j in range(cols + 1):
        x = l0 + (_px(80) - thick) * j // cols
        img[t0:t1, x : x + thick] = INK
    return img


def scatter(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    img = blank()
    side = 8
    ys = rng.integers(0, img.shape[0] - side, 3000)
    xs = rng.integers(0, img.shape[1] - side, 3000)
    for y, x in zip(ys, xs, strict=True):
        img[y : y + side, x : x + side] = INK
    return img


def smooth_photo(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    noise = rng.integers(0, 256, blank().shape, dtype=np.uint8)
    blurred = cv2.GaussianBlur(noise, (0, 0), 40)
    return cv2.normalize(blurred, None, 0, 255, cv2.NORM_MINMAX)


def one_short_line(seed: int = 0) -> np.ndarray:
    """A single line of about 20 mm: too little ink to measure a tilt."""
    rng = np.random.default_rng(seed)
    return text_page(rng, lines=1, width_mm=20 + 36, margin_mm=18)


def few_lines(seed: int = 0, count: int = 2) -> np.ndarray:
    return text_page(np.random.default_rng(seed), lines=count)


def skewed(pixels: np.ndarray, tenths: int) -> np.ndarray:
    """``pixels`` turned clockwise by ``tenths``/10 degrees about the centre, in the same frame,
    filled with paper. OpenCV's positive angle is counter-clockwise, hence the sign."""
    height, width = pixels.shape[:2]
    matrix = cv2.getRotationMatrix2D(((width - 1) / 2, (height - 1) / 2), -tenths / 10, 1.0)
    fill = (PAPER,) * 3
    return cv2.warpAffine(pixels, matrix, (width, height), flags=cv2.INTER_LINEAR, borderValue=fill)


def two_skews(seed: int = 0, tilts: tuple[int, int] = (40, -40)) -> np.ndarray:
    """Two blocks of text, the top one turned clockwise by ``tilts[0]`` tenths, the bottom one by
    ``tilts[1]``."""
    rng = np.random.default_rng(seed)
    half = text_page(rng, height_mm=HEIGHT_MM / 2, margin_mm=14)
    return np.vstack([skewed(half, tilts[0]), skewed(half, tilts[1])])


def loaded(pixels: np.ndarray, *, dpi: int = DPI) -> LoadedPage:
    """A grey page around ``pixels``."""
    return LoadedPage(pixels, ColourMode.GREY, dpi)


def rgb(pixels: np.ndarray, *, dpi: int = DPI) -> LoadedPage:
    """A colour page whose three channels are ``pixels``."""
    return LoadedPage(np.dstack([pixels] * 3), ColourMode.COLOUR, dpi)


def dashed_blocks(tilts: tuple[int, int]) -> np.ndarray:
    """Two blocks of thin dashed lines (a narrow peak in the profile), turned by ``tilts``."""
    half = np.full((_px(HEIGHT_MM / 2), _px(WIDTH_MM)), PAPER, np.uint8)
    for top in range(_px(14), half.shape[0] - _px(14), _px(4)):
        for left in range(_px(14), half.shape[1] - _px(16), _px(3)):
            half[top : top + 2, left : left + _px(2)] = INK
    return np.vstack([skewed(half, tilts[0]), skewed(half, tilts[1])])
