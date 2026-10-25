"""Synthetic pages for the document crop tests: one real raw page, left half black."""

from dataclasses import replace
from pathlib import Path

import numpy as np
from PIL import Image

from fastfoto_linux.documents.auto_colour import ColourDecision, ColourReason
from fastfoto_linux.documents.draft import DocumentDraft, PageAnalysis, TrimBox
from fastfoto_linux.documents.modes import ColourMode

WIDTH, HEIGHT, DPI = 1200, 1800, 300  # a 4 x 6 inch page


def crop_draft(folder: Path, pages: int = 2) -> DocumentDraft:
    """Raw pages in ``folder`` (untrimmed, left half black, right half white) and their draft."""
    pixels = np.full((HEIGHT, WIDTH, 3), 255, dtype=np.uint8)
    pixels[:, : WIDTH // 2] = 0
    rows = []
    for number in range(1, pages + 1):
        path = folder / f"page-{number:04d}.png"
        Image.fromarray(pixels).save(path, dpi=(DPI, DPI))
        info = path.stat()
        rows.append(
            PageAnalysis(
                number=number,
                name=path.name,
                size=info.st_size,
                mtime_ns=info.st_mtime_ns,
                dpi=DPI,
                trim=TrimBox(0, 0, 0, 0, False),
                blank=False,
                thumb=None,
                colour=ColourDecision(ColourMode.COLOUR, ColourMode.GREY, ColourReason.FAINT_MARKS),
            )
        )
    return replace(
        DocumentDraft(tuple(rows), folder, duplex=False, keep_blank=True),
    )
