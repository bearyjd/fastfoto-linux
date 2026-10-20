"""Small rights-cleared synthetic Auto pages; no external or private image inputs."""

import hashlib
from pathlib import Path

import numpy as np
from PIL import Image

from fastfoto_linux.documents.loader import LoadedPage
from fastfoto_linux.documents.modes import ColourMode
from fastfoto_linux.documents.units import mm_to_px
from tests.documents.helpers import image_object, reader

PAGE_WIDTH_MM = 80.0
PAGE_HEIGHT_MM = 100.0


def auto_page(case: str = "text", dpi: int = 100) -> LoadedPage:
    """Return a new physical-size page with a named synthetic preservation challenge."""
    shape = (mm_to_px(PAGE_HEIGHT_MM, dpi), mm_to_px(PAGE_WIDTH_MM, dpi))
    pixels = np.full((*shape, 3), 255, np.uint8)
    for row in range(5):
        top = mm_to_px(15 + row * 10, dpi)
        pixels[top : top + mm_to_px(0.5, dpi), mm_to_px(12, dpi) : mm_to_px(55, dpi)] = 0
    y, x = mm_to_px(75, dpi), mm_to_px(65, dpi)
    if case == "stamp":
        side = mm_to_px(2, dpi)
        pixels[y : y + side, x : x + side] = (20, 60, 210)
    elif case == "red_stroke":
        pixels[y : y + mm_to_px(0.25, dpi), x : x + mm_to_px(4, dpi)] = (210, 25, 25)
    elif case == "gradient":
        gradient = np.linspace(35, 225, mm_to_px(30, dpi), dtype=np.uint8)
        pixels[y - len(gradient) : y, x - len(gradient) : x] = gradient[None, :, None]
    elif case == "faint":
        pixels[y : y + mm_to_px(0.25, dpi), mm_to_px(10, dpi) : x] = 225
    elif case == "reversed":
        pixels[y - mm_to_px(12, dpi) : y, mm_to_px(10, dpi) : x] = 105
        pixels[y - mm_to_px(7, dpi) : y - mm_to_px(6.5, dpi), mm_to_px(15, dpi) : x] = 165
    elif case == "sepia":
        pixels[np.all(pixels == 255, axis=2)] = (245, 225, 190)
    elif case == "neutral_noise":
        rng = np.random.default_rng(27)
        neutral = rng.integers(248, 256, size=shape, dtype=np.uint8)
        pixels[np.all(pixels == 255, axis=2)] = np.repeat(neutral[:, :, None], 3, axis=2)[
            np.all(pixels == 255, axis=2)
        ]
    elif case == "blank":
        pixels.fill(255)
    elif case != "text":
        raise ValueError(f"unknown synthetic Auto page {case!r}")
    return LoadedPage(pixels, ColourMode.COLOUR, dpi)


def write_auto_pages(folder: Path, cases: tuple[str, ...]) -> tuple[Path, ...]:
    """Write only newly synthesized RGB PNGs into this test's temporary directory."""
    folder.mkdir()
    paths = []
    for number, case in enumerate(cases, 1):
        page = auto_page(case)
        path = folder / f"page-{number:04d}.png"
        Image.fromarray(page.pixels).save(path, dpi=(page.dpi, page.dpi))
        paths.append(path)
    return tuple(paths)


def source_hashes(pages: tuple[Path, ...]) -> tuple[str, ...]:
    return tuple(hashlib.sha256(path.read_bytes()).hexdigest() for path in pages)


def pdf_modes(path: Path) -> list[str]:
    document = reader(path.read_bytes())
    modes = []
    for index in range(len(document.pages)):
        image = image_object(document, index)
        modes.append("bw" if image["/BitsPerComponent"] == 1 else str(image["/ColorSpace"]))
    return modes
