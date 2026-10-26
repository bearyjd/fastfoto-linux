"""Shared by the ``--cleanup`` CLI tests: a generated shaded page, what the PDF should hold, and
spies on the encoders. Every run here has OCR off."""

import io
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pypdf
import pytest

from fastfoto_linux.documents import encode, write
from fastfoto_linux.documents.analyse import analyse_document
from fastfoto_linux.documents.draft import PageEdit
from fastfoto_linux.documents.encode import render_page
from fastfoto_linux.documents.loader import load_page
from fastfoto_linux.documents.modes import CleanupPolicy, ColourMode, ColourPolicy
from fastfoto_linux.documents.page_crop import edited_page
from fastfoto_linux.session.raw import list_pages
from tests.doc_synth import write_png
from tests.documents import cleanup_fixtures as fx
from tests.documents.store_helpers import store_settings

OCR_OFF = ["--ocr", "off", "--simplex"]
OFF, LIGHT, STRONG = CleanupPolicy.OFF, CleanupPolicy.LIGHT, CleanupPolicy.STRONG


def shaded_pages(folder: Path, count: int = 1) -> list[Path]:
    """``count`` copies of the generated A6 shaded paper page at 300 dpi, as page-NNNN.png."""
    folder.mkdir(parents=True, exist_ok=True)
    pixels = fx.shaded_paper().pixels
    return [
        write_png(folder / f"page-{n:04d}.png", pixels, dpi=fx.DPI) for n in range(1, count + 1)
    ]


def raw_folder_of(parent: Path, count: int = 1) -> tuple[Path, tuple[Path, ...]]:
    """A private ``.raw/<stamp>`` folder of shaded pages, and the pages ``list_pages`` finds."""
    folder = parent / ".raw" / "20261025T120000Z"
    folder.mkdir(parents=True, mode=0o700)
    shaded_pages(folder, count)
    return folder, list_pages(folder)


def expected_pixels(
    page: Path,
    mode: ColourMode,
    cleanup: CleanupPolicy,
    edit: PageEdit | None = None,
    out: Path | None = None,
) -> np.ndarray:
    """The pixels the PDF page must hold: ``render_page(edited_page(trim(raw)), mode, cleanup)``."""
    settings = store_settings(out or page.parent, duplex=False, colour=ColourPolicy.GREY)
    analysed = analyse_document([page], replace(settings, cleanup=OFF), encode=False)
    analysis = analysed.pages[0]
    trimmed = analysis.trim.apply(load_page(page, fallback_dpi=analysis.dpi))
    return render_page(edited_page(trimmed, edit or PageEdit()), mode, cleanup)


class EncoderSpy:
    """Records the pixels given to ``encode._jpeg``, the bytes ``encode._group4`` returned, the
    paper cleanup level of each ``write.encode_page`` call and the calls of ``write._read_page``."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.jpegs: list[np.ndarray] = []
        self.g4: list[bytes] = []
        self.levels: list[CleanupPolicy] = []
        self.reads = 0
        jpeg, group4 = encode._jpeg, encode._group4
        encode_page, read_page = write.encode_page, write._read_page

        def spy_jpeg(pixels: np.ndarray, dpi: int) -> bytes:
            self.jpegs.append(pixels.copy())
            return jpeg(pixels, dpi)

        def spy_group4(white: np.ndarray, dpi: int) -> bytes:
            data = group4(white, dpi)
            self.g4.append(data)
            return data

        def spy_encode(page: Any, mode: Any, cleanup: CleanupPolicy, **kwargs: Any) -> Any:
            self.levels.append(cleanup)
            return encode_page(page, mode, cleanup, **kwargs)

        def spy_read(*args: Any, **kwargs: Any) -> Any:
            self.reads += 1
            return read_page(*args, **kwargs)

        monkeypatch.setattr(encode, "_jpeg", spy_jpeg)
        monkeypatch.setattr(encode, "_group4", spy_group4)
        monkeypatch.setattr(write, "encode_page", spy_encode)
        monkeypatch.setattr(write, "_read_page", spy_read)


def pdf_page_sizes(path: Path) -> list[tuple[float, float]]:
    pdf = pypdf.PdfReader(io.BytesIO(path.read_bytes()))
    return [(float(page.mediabox.width), float(page.mediabox.height)) for page in pdf.pages]
