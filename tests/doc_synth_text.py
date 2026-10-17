"""Pale printed text for the blank-page tests, set in the font that ships with Pillow.

A scanner that blurs light grey type leaves a page that is plainly written on, yet only the thick
parts of the letters (the stems) stand out against the paper by the detector's contrast: each
stem alone is a straight, thin, faint stroke. ``pale_text_page`` draws such a page: the text is
black ink at 4 times the resolution, shrunk and blurred, then lightened so that its darkest pixel
is exactly ``darkest``. ``with_serif_text`` draws the same thing without a font: letters that are
a stem in the faint tone and a hairline too pale to count.
"""

import io
import math
from dataclasses import replace

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from fastfoto_linux.documents.loader import LoadedPage
from fastfoto_linux.documents.modes import ColourMode
from tests.doc_synth import MM_PER_INCH, Scene, _draw, px

SUPERSAMPLE = 4
POINTS_PER_INCH = 72
PAPER = 243
PAPER_NOISE = 3
LEADING = 1.4  # the distance between lines, in type sizes (a type size is 0.42 mm per point)
MM_PER_POINT = MM_PER_INCH / POINTS_PER_INCH
PARAGRAPH = (
    "Dear Sir or Madam, I am writing to confirm that the",
    "package was delivered on the fourteenth of October and",
    "that the contents were as described in the invoice.",
)
SERIF_STEM_MM = 0.28
SERIF_STEM_HEIGHT_MM = 2.6
SERIF_ROW_MM = 5.5
SERIF_HAIRLINE_MM = 0.07
SERIF_HAIRLINE_TONE = 226  # 14 levels darker than the paper: far under the contrast of a mark
SERIF_PITCH_MM = 2.1
SERIF_WORD_LETTERS = 5
SERIF_SPACE_MM = 1.6


def font_of(points: float, dpi: int) -> ImageFont.FreeTypeFont:
    """The bundled font at ``points`` on a page of ``dpi``, on the supersampled canvas."""
    font = ImageFont.load_default(size=max(1, round(points / POINTS_PER_INCH * dpi * SUPERSAMPLE)))
    assert isinstance(font, ImageFont.FreeTypeFont), "Pillow has no FreeType: no outline font"
    return font


def paragraph(
    points: float, x_mm: float = 8.0, y_mm: float = 6.0
) -> list[tuple[float, float, str]]:
    """The three lines of ``PARAGRAPH`` as (x, y, text), at ``LEADING`` times the type size."""
    step = points * MM_PER_POINT * LEADING
    return [(x_mm, y_mm + number * step, line) for number, line in enumerate(PARAGRAPH)]


def pale_text_page(  # noqa: PLR0913
    dpi: int,
    lines: list[tuple[float, float, str]],
    *,
    points: float,
    darkest: int,
    blur_mm: float,
    size_mm: tuple[float, float] = (130.0, 40.0),
    jpeg_quality: int | None = None,
) -> LoadedPage:
    """A colour page of ``size_mm`` with ``lines`` (x, y, text) set in ``points`` type, blurred (a
    Gaussian of ``blur_mm``) and pale enough that the darkest pixel is ``darkest`` (JPEG-coded
    if asked)."""
    width, height = (round(side * dpi / MM_PER_INCH) for side in size_mm)
    canvas = Image.new("L", (width * SUPERSAMPLE, height * SUPERSAMPLE), 0)
    font, scale = font_of(points, dpi), dpi / MM_PER_INCH * SUPERSAMPLE
    draw = ImageDraw.Draw(canvas)
    for x_mm, y_mm, text in lines:
        draw.text((x_mm * scale, y_mm * scale), text, fill=255, font=font)
    coverage = canvas.resize((width, height), Image.Resampling.BOX).filter(
        ImageFilter.GaussianBlur(blur_mm * dpi / MM_PER_INCH)
    )
    ink = np.asarray(coverage, dtype=np.float64) / 255.0
    noise = np.random.default_rng(0).integers(-PAPER_NOISE, PAPER_NOISE + 1, (height, width))
    paper = PAPER + noise.astype(np.float64)
    pixels = np.clip(np.rint(paper - (paper.mean() - darkest) * ink / ink.max()), 0, 255)
    page = pixels.astype(np.uint8)
    rgb = np.stack([page] * 3, axis=2)
    if jpeg_quality is not None:
        buffer = io.BytesIO()
        Image.fromarray(rgb).save(buffer, "JPEG", quality=jpeg_quality)
        rgb = np.asarray(Image.open(buffer)).copy()
    return LoadedPage(rgb, ColourMode.COLOUR, dpi)


def with_serif_text(  # noqa: PLR0913
    scene: Scene, x_mm: float, y_mm: float, letters: int, *, tone: int, rows: int = 1
) -> Scene:
    """``rows`` lines of ``letters`` letters, each a stem (``SERIF_STEM_MM`` wide, in ``tone``)
    with a hairline bowl at its side that is too pale to be a mark: a serif face once it is
    blurred. Letters are ``SERIF_PITCH_MM`` apart, in words of ``SERIF_WORD_LETTERS``."""
    dpi, left = scene.dpi, scene.paper_x[0]
    stem, hairline = max(1, px(SERIF_STEM_MM, dpi)), max(1, px(SERIF_HAIRLINE_MM, dpi))

    def at(x: float, y: float) -> tuple[int, int]:
        return left + px(x, dpi), px(y, dpi)

    def paint(draw: ImageDraw.ImageDraw) -> None:
        for row in range(rows):
            top, x = y_mm + row * SERIF_ROW_MM, x_mm
            for number in range(letters):
                draw.line(
                    [at(x, top), at(x, top + SERIF_STEM_HEIGHT_MM)], fill=(tone,) * 3, width=stem
                )
                bowl = [
                    at(
                        x + 0.9 * math.sin(a),
                        top + SERIF_STEM_HEIGHT_MM * (0.5 + 0.5 * math.cos(a)),
                    )
                    for a in np.linspace(0.3, 3.0, 12)
                ]
                draw.line(bowl, fill=(SERIF_HAIRLINE_TONE,) * 3, width=hairline, joint="curve")
                last = number % SERIF_WORD_LETTERS == SERIF_WORD_LETTERS - 1
                x += SERIF_PITCH_MM + (SERIF_SPACE_MM if last else 0.0)

    return replace(scene, image=_draw(scene, paint))
