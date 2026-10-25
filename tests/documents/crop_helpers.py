"""Pages for the crop tests: generated in code, seeded, with a marker in each corner."""

from dataclasses import replace
from pathlib import Path

import numpy as np

from fastfoto_linux.documents.draft import DocumentDraft, PageAnalysis, TrimBox
from fastfoto_linux.documents.encode import encode_page
from fastfoto_linux.documents.loader import LoadedPage, load_page
from fastfoto_linux.documents.modes import ColourMode
from fastfoto_linux.documents.units import mm_to_px
from tests.doc_synth import write_png

DPI = 300
A6_MM = (105, 148)
MARKER_MM = 3
TRIM = TrimBox(left=7, right=5, top=9, bottom=11)
CORNER_VALUES = (10, 80, 150, 220)  # top left, top right, bottom left, bottom right


def marked_pixels(kind: ColourMode, *, dpi: int = DPI, seed: int = 0) -> np.ndarray:
    """A noisy light A6 page with a dark 3 x 3 mm marker in each corner, each a different value."""
    rng = np.random.default_rng(seed)
    width, height = (mm_to_px(mm, dpi) for mm in A6_MM)
    page = rng.integers(200, 256, size=(height, width), dtype=np.uint8)
    size = mm_to_px(MARKER_MM, dpi)
    tl, tr, bl, br = CORNER_VALUES
    page[:size, :size] = tl
    page[:size, -size:] = tr
    page[-size:, :size] = bl
    page[-size:, -size:] = br
    if kind is ColourMode.GREY:
        return page
    return np.stack([page, np.clip(page.astype(int) + 7, 0, 255).astype(np.uint8), page], axis=2)


def loaded(kind: ColourMode, *, dpi: int = DPI) -> LoadedPage:
    return LoadedPage(marked_pixels(kind, dpi=dpi), kind, dpi)


def crop_draft(
    folder: Path, kind: ColourMode, *, encoded: ColourMode | None = None
) -> DocumentDraft:
    """A one page draft over a PNG in ``folder`` with a fixed trim box. ``encoded`` is the mode of
    the bytes the page carries (None: it carries none)."""
    folder.mkdir(parents=True, exist_ok=True)
    path = write_png(folder / "page-0001.png", marked_pixels(kind), dpi=DPI)
    page = PageAnalysis(
        number=1,
        name=path.name,
        size=path.stat().st_size,
        mtime_ns=1,
        dpi=DPI,
        trim=TRIM,
        blank=False,
    )
    if encoded is not None:
        trimmed = TRIM.apply(load_page(path, fallback_dpi=DPI))
        page = replace(page, encoded=encode_page(trimmed, encoded))
    return DocumentDraft(pages=(page,), raw_dir=folder, duplex=False, keep_blank=True)


def trimmed_size(kind: ColourMode) -> tuple[int, int]:
    """The (width, height) of the trimmed marked page."""
    height, width = TRIM.apply(loaded(kind)).pixels.shape[:2]
    return width, height
