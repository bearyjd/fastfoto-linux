"""Shared helpers for the documents tests: pages from synthetic scenes, and reading PDFs back."""

import io
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pypdf

from fastfoto_linux.documents.loader import LoadedPage
from fastfoto_linux.documents.modes import ColourMode
from tests.doc_synth import Scene, paper_scene, to_bilevel, to_grey, with_text, write_png

FIXED_TIME = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
POINTS_PER_INCH = 72
DPI = 100


def colour_page(scene: Scene) -> LoadedPage:
    return LoadedPage(scene.image, ColourMode.COLOUR, scene.dpi)


def grey_page(scene: Scene) -> LoadedPage:
    return LoadedPage(to_grey(scene.image), ColourMode.GREY, scene.dpi)


def bw_page(scene: Scene) -> LoadedPage:
    return LoadedPage(to_bilevel(scene.image), ColourMode.BW, scene.dpi)


def pages_of(scene: Scene) -> dict[str, LoadedPage]:
    """The same scene as each kind of page the loader can produce."""
    return {"colour": colour_page(scene), "grey": grey_page(scene), "bw": bw_page(scene)}


def write_scene(path: Path, scene: Scene, *, dpi: int | None = None) -> Path:
    """Save a scene as an RGB PNG (``dpi`` defaults to the scene's)."""
    return write_png(path, scene.image, dpi=dpi if dpi is not None else scene.dpi)


def reader(data: bytes) -> pypdf.PdfReader:
    return pypdf.PdfReader(io.BytesIO(data))


def image_object(pdf: pypdf.PdfReader, index: int) -> Any:
    """The image XObject of page ``index`` (each page holds exactly one)."""
    xobjects = pdf.pages[index]["/Resources"]["/XObject"]
    assert len(xobjects) == 1
    return next(iter(xobjects.values())).get_object()


def page_size_pt(pdf: pypdf.PdfReader, index: int) -> tuple[float, float]:
    box = pdf.pages[index].mediabox
    return float(box.width), float(box.height)


def pdf_pixels(pdf: pypdf.PdfReader, index: int) -> np.ndarray:
    """Decode the embedded image of a page to an array (grey, or 0/255 for 1-bit)."""
    image = pdf.pages[index].images[0].image
    return np.asarray(image.convert("L"))


def expected_points(pixels: int, dpi: int) -> float:
    return pixels * POINTS_PER_INCH / dpi


def text_scene(seed: int = 0, dpi: int = DPI, **kwargs: Any) -> Scene:
    """A page with a few lines of text-like marks."""
    scene = paper_scene(dpi=dpi, seed=seed, **kwargs)
    for row in range(6):
        scene = with_text(scene, 25, 30 + row * 10, 25)
    return scene


def blank_scene(seed: int = 0, dpi: int = DPI) -> Scene:
    return paper_scene(dpi=dpi, seed=seed)


def write_pages(folder: Path, scenes: list[Scene]) -> list[Path]:
    """Save scenes as ``page-01.png``, ``page-02.png`` ... in ``folder``."""
    folder.mkdir(exist_ok=True)
    return [write_scene(folder / f"page-{n:02d}.png", scene) for n, scene in enumerate(scenes, 1)]
