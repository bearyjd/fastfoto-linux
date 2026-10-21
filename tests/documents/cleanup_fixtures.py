"""Generated pages for the paper-cleanup tests: A6 at 300 dpi (so the work grid is f = 2), seeded.

Every fixture is an RGB page; a grey page is ``pixels[..., 0]`` where the page is neutral. The
masks name the pixels that were drawn, so a test can say what must survive.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

import numpy as np

from fastfoto_linux.documents.units import mm_to_px

DPI = 300
WIDTH_MM, HEIGHT_MM = 105, 148
PAPER = 232
INK = 30
SEED = 20261020

Point = tuple[int, int]


@dataclass(frozen=True)
class Fixture:
    name: str
    pixels: np.ndarray
    masks: Mapping[str, np.ndarray] = field(default_factory=dict)
    # (mark point, paper point beside it) in (row, column), for the contrast checks
    samples: tuple[tuple[Point, Point], ...] = ()
    dpi: int = DPI


def px(mm: float, dpi: int = DPI) -> int:
    return mm_to_px(mm, dpi)


def canvas(paper: int | tuple[int, int, int] | np.ndarray, *, dpi: int = DPI) -> np.ndarray:
    height, width = px(HEIGHT_MM, dpi), px(WIDTH_MM, dpi)
    if isinstance(paper, np.ndarray):
        return np.repeat(paper[..., None], 3, axis=2).astype(np.uint8)
    page = np.empty((height, width, 3), np.uint8)
    page[:] = paper
    return page


def add_text(  # noqa: PLR0913
    page: np.ndarray,
    rng: np.random.Generator,
    ink: tuple[int, int, int] = (INK, INK, INK),
    *,
    top_mm: float = 14,
    lines: int = 6,
    dpi: int = DPI,
) -> np.ndarray:
    """Rows of short upright strokes (4 px wide) and bars; returns the mask of what was drawn."""
    mask = np.zeros(page.shape[:2], bool)
    margin = px(12, dpi)
    width = page.shape[1] - margin
    for line in range(lines):
        y = px(top_mm, dpi) + line * px(6, dpi)
        x = margin
        while x < width - 60:
            stroke = int(rng.integers(20, 50))
            page[y : y + 25, x : x + 4] = ink
            mask[y : y + 25, x : x + 4] = True
            page[y + 10 : y + 13, x : x + stroke] = ink
            mask[y + 10 : y + 13, x : x + stroke] = True
            x += stroke + int(rng.integers(8, 20))
    return mask


def _rng(offset: int = 0) -> np.random.Generator:
    return np.random.default_rng(SEED + offset)


def shaded_paper() -> Fixture:
    rng = _rng(1)
    height, width = px(HEIGHT_MM), px(WIDTH_MM)
    ramp = np.rint(np.linspace(235, 205, width))[None, :] + np.zeros((height, 1))
    paper = np.clip(ramp + rng.integers(-3, 4, (height, width)), 0, 255)
    page = canvas(paper)
    return Fixture("shaded_paper", page, {"ink": add_text(page, rng)})


def _text_page(name: str, paper: tuple[int, int, int], ink: tuple[int, int, int]) -> Fixture:
    rng = _rng(len(name))
    page = canvas(paper)
    return Fixture(name, page, {"ink": add_text(page, rng, ink)})


def coloured_stock() -> Fixture:
    return _text_page("coloured_stock", (200, 215, 235), (30, 30, 45))


def cream_paper() -> Fixture:
    return _text_page("cream_paper", (240, 232, 210), (30, 30, 30))


def already_white() -> Fixture:
    return _text_page("already_white", (250, 250, 250), (INK, INK, INK))


def dark_page() -> Fixture:
    return _text_page("dark_page", (120, 120, 120), (10, 10, 10))


def faint_pencil() -> Fixture:
    page = canvas(PAPER)
    stroke = px(0.3)
    mask = np.zeros(page.shape[:2], bool)
    for row, long in ((300, 240), (600, 120)):
        page[row : row + stroke, 200 : 200 + long] = PAPER - 35
        mask[row : row + stroke, 200 : 200 + long] = True
    samples = (((302, 260), (302 - 30, 260)), ((602, 240), (602 + 30, 240)))
    return Fixture("faint_pencil", page, {"pencil": mask}, samples)


def red_annotation() -> Fixture:
    rng = _rng(5)
    page = canvas(PAPER)
    add_text(page, rng, top_mm=14, lines=2)
    red = add_text(page, rng, (200, 30, 30), top_mm=40, lines=3)
    return Fixture("red_annotation", page, {"red": red})


def punctuation_dot() -> Fixture:
    page = canvas(PAPER)
    size = px(0.3)
    mask = np.zeros(page.shape[:2], bool)
    for y, x in ((400, 300), (900, 700), (1300, 450)):
        page[y : y + size, x : x + size] = 40
        mask[y : y + size, x : x + size] = True
    return Fixture("punctuation_dot", page, {"dot": mask})


def _ring(shape: tuple[int, int], centre: Point, radius_mm: float, width_mm: float) -> np.ndarray:
    yy, xx = np.ogrid[: shape[0], : shape[1]]
    distance = np.hypot(yy - centre[0], xx - centre[1])
    return (distance >= px(radius_mm) - px(width_mm) // 2) & (
        distance <= px(radius_mm) + px(width_mm) // 2
    )


def stamp() -> Fixture:
    page = canvas(PAPER)
    shape = page.shape[:2]
    pink = _ring(shape, (500, 400), 12, 0.7)
    grey = _ring(shape, (1100, 700), 12, 0.7)
    page[pink] = (230, 150, 170)
    page[grey] = round(0.85 * PAPER)
    samples = (((1100 - px(12), 700), (1100 - px(12) - 30, 700)),)
    return Fixture("stamp", page, {"pink": pink, "grey_ring": grey}, samples)


def ruled_table() -> Fixture:
    rng = _rng(8)
    page = canvas(PAPER)
    thin = px(0.2)
    rules = np.zeros(page.shape[:2], bool)
    faint = np.zeros(page.shape[:2], bool)
    for index, row in enumerate(range(150, 1500, 90)):
        mask = rules if index % 2 == 0 else faint
        page[row : row + thin, 100:1100] = 120 if index % 2 == 0 else 200
        mask[row : row + thin, 100:1100] = True
    add_text(page, rng, lines=1, top_mm=2)
    samples = (((240 + 1, 600), (240 + 1 + 30, 600)),)  # the faint rule at row 240
    return Fixture("ruled_table", page, {"rules120": rules, "faint_rules": faint}, samples)


def photo_region() -> Fixture:
    rng = _rng(9)
    page = canvas(PAPER)
    height, width = px(40), px(50)
    left = px(27)
    mid = rng.integers(60, 141, (height, width))
    ramp = np.linspace(185, 230, width)[None, :] + rng.integers(-12, 13, (height, width))
    masks = {}
    for name, top_mm, tone in (("photo_mid", 20, mid), ("photo_high", 80, ramp)):
        top = px(top_mm)
        page[top : top + height, left : left + width] = np.clip(tone, 0, 255)[..., None]
        inset = px(10)
        core = np.zeros(page.shape[:2], bool)
        core[top + inset : top + height - inset, left + inset : left + width - inset] = True
        masks[name] = core
    return Fixture("photo_region", page, masks)


FIXTURES: Mapping[str, Callable[[], Fixture]] = {
    "shaded_paper": shaded_paper,
    "coloured_stock": coloured_stock,
    "cream_paper": cream_paper,
    "faint_pencil": faint_pencil,
    "red_annotation": red_annotation,
    "punctuation_dot": punctuation_dot,
    "stamp": stamp,
    "ruled_table": ruled_table,
    "already_white": already_white,
    "photo_region": photo_region,
    "dark_page": dark_page,
}


def noise_page(seed: int, height: int = 211, width: int = 187, dpi: int = DPI) -> Fixture:
    """Uniform random RGB noise: the worst case for a window of any kind."""
    rng = np.random.default_rng(seed)
    return Fixture(
        f"noise_{seed}", rng.integers(0, 256, (height, width, 3), dtype=np.uint8), dpi=dpi
    )


def odd_size_page(dpi: int = 600, height: int = 877, width: int = 1003) -> Fixture:
    """A shaded page with text and a high-key block, sized to fit neither f nor the cell size."""
    rng = np.random.default_rng(SEED + 11)
    ramp = np.linspace(236, 204, width)[None, :] + np.zeros((height, 1))
    paper = np.clip(np.rint(ramp) + rng.integers(-3, 4, (height, width)), 0, 255)
    page = np.repeat(paper[..., None], 3, axis=2).astype(np.uint8)
    top, bottom = height * 34 // 100, height * 68 // 100
    left, right = width // 4, width * 7 // 10
    block = np.linspace(185, 230, right - left)[None, :, None]
    page[top:bottom, left:right] = np.clip(block, 0, 255)
    page[height // 9 : height // 9 + height // 30, width // 17 : width * 9 // 10 : 7] = INK
    page[height * 8 // 10 : height * 87 // 100, width // 10 : width * 4 // 10] = (200, 30, 30)
    return Fixture(f"odd_{dpi}_{height}x{width}", page, dpi=dpi)
