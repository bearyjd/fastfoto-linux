"""Generated black-and-white pages for the despeckle tests: A6 at 300 dpi (600 dpi where noted),
seeded. A page is a bool array, True where white; ``ink`` draws black."""

import numpy as np

DPI = 300
A6_MM = (105, 148)
Box = tuple[int, int, int, int]  # row, column, height, width


def px(mm: float, dpi: int = DPI) -> int:
    return round(mm * dpi / 25.4)


def blank(height: int | None = None, width: int | None = None, dpi: int = DPI) -> np.ndarray:
    return np.ones((height or px(A6_MM[1], dpi), width or px(A6_MM[0], dpi)), dtype=bool)


def ink(page: np.ndarray, row: int, col: int, height: int = 1, width: int = 1) -> None:
    page[row : row + height, col : col + width] = False


def dust(seed: int = 7) -> np.ndarray:
    """40 specks of 1 to 3 px, each on its own cell of an 80 px grid (over 5 mm from any ink)."""
    rng = np.random.default_rng(seed)
    page = blank()
    rows, cols = page.shape[0] // 80, page.shape[1] // 80
    for cell in rng.choice(rows * cols, size=40, replace=False):
        size = int(rng.integers(1, 4))
        ink(
            page,
            int(cell // cols) * 80 + int(rng.integers(8, 16)),
            int(cell % cols) * 80 + int(rng.integers(8, 16)),
            size,
            size,
        )
    return page


def text_line() -> np.ndarray:
    """Stems with periods (2x2 and 3x3) 0.4 mm after a stem, and i-dots 0.3 mm above stems."""
    page = blank()
    top, stem_h, stem_w = 300, 30, 4
    for index in range(12):
        col = 100 + index * 60
        ink(page, top, col, stem_h, stem_w)
        if index % 3 == 0:
            ink(page, top + stem_h - 2, col + stem_w + px(0.4), 2, 2)  # a period
        elif index % 3 == 1:
            ink(page, top + stem_h - 3, col + stem_w + px(0.4), 3, 3)
        else:
            ink(page, top - px(0.3) - 3, col, 3, 3)  # an i-dot above the stem
    return page


def colon() -> np.ndarray:
    page = blank()
    ink(page, 400, 500, 3, 3)
    ink(page, 408, 500, 3, 3)
    return page


def ellipsis() -> np.ndarray:
    page = blank()
    for index in range(3):
        ink(page, 400, 500 + index * 10, 3, 3)
    return page


def hairline() -> np.ndarray:
    """A 1 px horizontal rule and a 1 px diagonal rule."""
    page = blank()
    ink(page, 300, 100, 1, 400)
    for step in range(300):
        ink(page, 500 + step, 100 + step)
    return page


def diagonal_speck() -> np.ndarray:
    """Three pixels on a diagonal: one speck only when 8-connected."""
    page = blank()
    for step in range(3):
        ink(page, 600 + step, 600 + step)
    return page


def dotted_leader(pitch_mm: float) -> np.ndarray:
    """A row of 20 dots of 2x2 px, ``pitch_mm`` apart."""
    page = blank()
    for index in range(20):
        ink(page, 400, 100 + index * px(pitch_mm), 2, 2)
    return page


def halftone() -> np.ndarray:
    """2x2 dots at a 1 mm pitch (12 px) over 60 x 40 mm."""
    page = blank()
    for row in range(200, 200 + px(40), 12):
        for col in range(100, 100 + px(60), 12):
            ink(page, row, col, 2, 2)
    return page


def sparse_field() -> np.ndarray:
    """2x2 dots at a 3 mm pitch (35 px) over the whole page: more than 1000 isolated dots."""
    page = blank()
    for row in range(20, page.shape[0] - 20, 35):
        for col in range(20, page.shape[1] - 20, 35):
            ink(page, row, col, 2, 2)
    return page


def speck(size: int) -> np.ndarray:
    page = blank()
    ink(page, 500, 500, size, size)
    return page


def red_dot() -> tuple[np.ndarray, np.ndarray]:
    """(white, rgb source): an isolated 3x3 red dot, plus a dark grey 3x3 speck far from it."""
    source = np.full((*blank().shape, 3), 235, dtype=np.uint8)
    source[500:503, 500:503] = (220, 30, 30)
    source[900:903, 900:903] = (50, 50, 50)
    white = np.ones(blank().shape, dtype=bool)
    white[500:503, 500:503] = False
    white[900:903, 900:903] = False
    return white, source


def asymmetric() -> np.ndarray:
    """X (an L of 5 px in a 3x3 box) and a 1 px Y that lies in X's window while X is outside Y's:
    Y is removed in round 1, then X in round 2."""
    page = blank(400, 400)
    ink(page, 200, 100, 3, 1)  # X: left column
    ink(page, 202, 100, 1, 3)  # X: bottom row
    ink(page, 170, 132)  # Y: up and right, 30 px beyond X's box
    return page


def random_page(seed: int) -> tuple[np.ndarray, int]:
    """A seeded page of 300x300 to 1200x900 with specks, glyph blocks and rules, and its dpi."""
    rng = np.random.default_rng(seed)
    dpi = int(rng.choice([150, 200, 300, 600]))
    height, width = int(rng.integers(300, 901)), int(rng.integers(300, 1201))
    page = blank(height, width)
    for _ in range(int(rng.integers(0, 41))):
        size = int(rng.integers(1, 6))
        ink(page, int(rng.integers(0, height - 5)), int(rng.integers(0, width - 5)), size, size)
    for _ in range(int(rng.integers(0, 12))):
        ink(
            page,
            int(rng.integers(0, height - 40)),
            int(rng.integers(0, width - 40)),
            int(rng.integers(2, 40)),
            int(rng.integers(2, 40)),
        )
    for _ in range(int(rng.integers(0, 3))):
        ink(
            page,
            int(rng.integers(0, height)),
            int(rng.integers(0, width // 2)),
            1,
            int(rng.integers(20, width // 2)),
        )
    return page, dpi


def halftone_mask(dpi: int) -> np.ndarray:
    """An A4 page (True where white) whose black pixels are every other pixel of every other row:
    about a quarter of all pixels, each its own 8-connected component."""
    height, width = (3508, 2480) if dpi == 300 else (7016, 4960)
    white = np.ones((height, width), dtype=bool)
    white[::2, ::2] = False
    return white


def dense_page(seed: int) -> tuple[np.ndarray, int]:
    """A small seeded page of dot grids (pitch 2 to 4) with isolated specks around them."""
    rng = np.random.default_rng(seed)
    dpi = int(rng.choice([150, 300]))
    height, width = int(rng.integers(120, 260)), int(rng.integers(120, 260))
    page = blank(height, width)
    for _ in range(int(rng.integers(1, 4))):
        pitch = int(rng.integers(2, 5))
        top, left = int(rng.integers(0, height // 2)), int(rng.integers(0, width // 2))
        rows, cols = int(rng.integers(10, height // 2)), int(rng.integers(10, width // 2))
        page[top : top + rows : pitch, left : left + cols : pitch] = False
    for _ in range(int(rng.integers(5, 40))):
        size = int(rng.integers(1, 4))
        ink(page, int(rng.integers(0, height - 3)), int(rng.integers(0, width - 3)), size, size)
    return page, dpi
