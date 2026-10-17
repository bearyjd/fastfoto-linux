"""Print for the hole tests: page numbers, notes and body text set in real fonts, as a scanner
delivers them. A hole is grey (darkest 89 to 106 on real pages) and print is black (darkest 0 to
12), so none of this may ever be taken for a hole."""

import random
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import ImageFont

from tests.doc_synth import INK_TONE, MM_PER_INCH, PAPER_TONE, Scene, _draw, px
from tests.doc_synth_holes import SMALL_MM, Painter

PRINT_TONE = 10  # black print on a real page: darkest 0 to 12
POINTS_PER_INCH = 72
BUNDLED = "bundled"  # the font that ships with Pillow: present wherever the tests run
SYSTEM_FONTS = {  # Liberation Sans and Serif, where the system has them
    "sans": ("LiberationSans-Regular.ttf", "liberation-sans-fonts", "liberation", "liberation2"),
    "serif": ("LiberationSerif-Regular.ttf", "liberation-serif-fonts", "liberation", "liberation2"),
}
FONT_DIRS = (Path("/usr/share/fonts"), Path("/usr/share/fonts/truetype"))
# fmt: off
WORDS = (
    "the", "of", "and", "to", "in", "is", "that", "for", "it", "as", "was", "with", "be", "by",
    "on", "not", "this", "are", "or", "from", "at", "which", "but", "have", "an", "had", "they",
    "you", "were", "their", "one", "all", "we", "can", "her", "has", "there", "been", "if",
    "more", "when", "will", "would", "who", "so", "no", "out", "them", "some", "could", "time",
    "these", "two", "may", "then", "do", "first", "any", "my", "now", "such", "like", "our",
    "over", "man", "me",
)
# fmt: on


def font_file(name: str) -> Path | None:
    """The file of a system font, None when the system has no such font."""
    if name == BUNDLED:
        return None
    file, *folders = SYSTEM_FONTS[name]
    found = [base / folder / file for base in FONT_DIRS for folder in folders]
    return next((path for path in found if path.is_file()), None)


def _has(name: str) -> bool:
    return name == BUNDLED or font_file(name) is not None


FONTS = [
    pytest.param(name, marks=pytest.mark.skipif(not _has(name), reason=f"no {name} font"), id=name)
    for name in (BUNDLED, *SYSTEM_FONTS)
]


def font_of(name: str, points: float, dpi: int) -> ImageFont.FreeTypeFont:
    size = max(1, round(points / POINTS_PER_INCH * dpi))
    path = font_file(name)
    font = ImageFont.load_default(size=size) if path is None else ImageFont.truetype(path, size)
    assert isinstance(font, ImageFont.FreeTypeFont), "Pillow has no FreeType: no outline font"
    return font


def width_mm(text: str, points: float, dpi: int, font: str = BUNDLED) -> float:
    return font_of(font, points, dpi).getlength(text) * MM_PER_INCH / dpi


def printed(  # noqa: PLR0913
    text: str,
    x_mm: float,
    baseline_mm: float,
    points: float,
    *,
    font: str = BUNDLED,
    tone: int = PRINT_TONE,
) -> Painter:
    """``text`` set in ``font`` with its baseline ``baseline_mm`` from the paper's top and its
    left end ``x_mm`` from the paper's left edge."""

    def paint(scene: Scene) -> Scene:
        face = font_of(font, points, scene.dpi)
        origin = (
            scene.paper_x[0] + px(x_mm, scene.dpi),
            scene.paper_top + px(baseline_mm, scene.dpi),
        )
        return replace(
            scene,
            image=_draw(
                scene,
                lambda draw: draw.text(origin, text, font=face, fill=(tone,) * 3, anchor="ls"),
            ),
        )

    return paint


def pen_note(glyph: str, x_mm: float, baseline_mm: float, points: float, font: str) -> Painter:
    """One glyph of handwriting: dark ink, but not as black as print."""
    return printed(glyph, x_mm, baseline_mm, points, font=font, tone=INK_TONE)


def body_text(  # noqa: PLR0913
    seed: int,
    *,
    paper_mm: tuple[float, float] = SMALL_MM,
    margin_mm: float = 12.0,
    top_mm: float = 12.0,
    bottom_mm: float = 24.0,
    points: float = 10.0,
    font: str = BUNDLED,
) -> Painter:
    """Lines of words from ``top_mm`` down to ``bottom_mm`` above the paper's foot."""
    width, height = paper_mm
    rows = random.Random(seed)

    def paint(scene: Scene) -> Scene:
        face = font_of(font, points, scene.dpi)
        step, y, done = points * MM_PER_INCH / POINTS_PER_INCH * 1.4, top_mm, scene
        while y < height - bottom_mm:
            line = ""
            while True:
                word = rows.choice(WORDS)
                extra = " " + word if line else word
                if face.getlength(line + extra) * MM_PER_INCH / scene.dpi > width - 2 * margin_mm:
                    break
                line += extra
            done = printed(line, margin_mm, y, points, font=font)(done)
            y += step
        return done

    return paint


def page_numbers(  # noqa: PLR0913
    front: str,
    back: str,
    *,
    points: float,
    dpi: int,
    font: str,
    where: str,
    paper_mm: tuple[float, float] = SMALL_MM,
    foot_mm: float = 8.0,
) -> tuple[Painter, Painter]:
    """The page numbers of a sheet, each at the same spot of its side's paper once the back is
    flipped: at the centre of the foot, or at the outer corner (right on the front, left on the
    back)."""
    width, height = paper_mm

    def at(text: str, *, left: bool) -> Painter:
        size = width_mm(text, points, dpi, font)
        x = (
            (width - size) / 2
            if where == "centre"
            else (foot_mm if left else width - foot_mm - size)
        )
        return printed(text, x, height - foot_mm, points, font=font)

    return at(front, left=False), at(back, left=True)


def with_ghost(scene: Scene, source: Scene, *, darkest: int, blur_mm: float = 0.3) -> Scene:
    """The ink of ``source``, the other side of the sheet, showing through the paper of ``scene``:
    mirrored, blurred by ``blur_mm`` and as pale as ``darkest`` at its darkest."""
    ink = np.clip(PAPER_TONE - source.image.min(axis=2).astype(np.float32), 0, None)
    ghost = cv2.GaussianBlur(np.fliplr(ink), (0, 0), max(0.1, blur_mm * scene.dpi / MM_PER_INCH))
    ghost *= (PAPER_TONE - darkest) / ghost.max()
    image = np.clip(scene.image.astype(np.float32) - ghost[..., None], 0, 255)
    return replace(scene, image=image.astype(np.uint8))
