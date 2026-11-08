"""Pages that try to make the deskew estimate say ``estimated`` when the turn would cut content.

Each case is a name and a builder of (pixels, dpi). ``test_deskew_adversarial`` pins the verdicts
of the estimate before the noise change (computed once on the code of that day, kept as literals).
"""

from collections.abc import Callable

import numpy as np

from tests.documents.deskew_fixtures import skewed, text_page

TILT = 80
Build = Callable[[], tuple[np.ndarray, int]]


def _page(dpi: int = 300) -> np.ndarray:
    return skewed(text_page(np.random.default_rng(3), dpi=dpi), TILT)


def _noisy(pixels: np.ndarray, sigma: float, seed: int = 11) -> np.ndarray:
    noise = np.random.default_rng(seed).normal(0, sigma, pixels.shape)
    return np.clip(pixels + noise, 0, 255).astype(np.uint8)


def corner_block(side: int, level: int) -> Build:
    def build() -> tuple[np.ndarray, int]:
        pixels = _page()
        pixels[:side, :side] = level
        return pixels, 300

    return build


def top_band(rows: int, level: int) -> Build:
    def build() -> tuple[np.ndarray, int]:
        pixels = _page()
        pixels[:rows, :] = level
        return pixels, 300

    return build


def ruled_line(level: int) -> Build:
    def build() -> tuple[np.ndarray, int]:
        pixels = _page()
        pixels[3:6, 100:-100] = level
        return pixels, 300

    return build


def textured_corner(side: int) -> Build:
    def build() -> tuple[np.ndarray, int]:
        pixels = _page()
        rng = np.random.default_rng(5)
        pixels[:side, -side:] = rng.integers(60, 230, (side, side), dtype=np.uint8)
        return pixels, 300

    return build


def noisy_mark(sigma: int, level: int) -> Build:
    def build() -> tuple[np.ndarray, int]:
        pixels = _noisy(_page(600), sigma)
        pixels[:24, :18] = level
        return pixels, 600

    return build


def noisy_block(sigma: int, level: int) -> Build:
    def build() -> tuple[np.ndarray, int]:
        pixels = _noisy(_page(), sigma)
        pixels[:300, :300] = level
        return pixels, 300

    return build


CASES: dict[str, Build] = {
    **{f"block{s}_{v}": corner_block(s, v) for s in (60, 200, 400) for v in (140, 180, 205, 225)},
    **{f"band{r}_{v}": top_band(r, v) for r in (40, 150, 300) for v in (190, 205, 225)},
    **{f"line_{v}": ruled_line(v) for v in (150, 200, 225)},
    **{f"texture{s}": textured_corner(s) for s in (100, 300)},
    **{f"mark{sg}_{v}": noisy_mark(sg, v) for sg in (6, 10) for v in (190, 150)},
    **{f"noisyblock{sg}_{v}": noisy_block(sg, v) for sg in (6, 10) for v in (150, 205)},
}
