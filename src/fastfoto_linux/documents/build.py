"""Turn page files into one PDF: load, trim, drop blanks, encode, assemble, OCR, publish."""

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from fastfoto_linux.documents.encode import encode_page  # noqa: F401
from fastfoto_linux.documents.loader import inspect_page, load_page  # noqa: F401
from fastfoto_linux.documents.modes import ColourMode
from fastfoto_linux.documents.ocr import (  # noqa: F401
    DEFAULT_LANGS,
    OcrMode,
    OcrOutcome,
    OcrStatus,
    run_ocr,
)

DEFAULT_NAME = "Document"


@dataclass(frozen=True)
class DocumentSettings:
    output_root: Path
    name: str = DEFAULT_NAME
    colour: ColourMode = ColourMode.COLOUR
    keep_blank: bool = False
    ocr: OcrMode = OcrMode.AUTO
    langs: str = DEFAULT_LANGS
    fallback_dpi: int | None = None
    ocr_timeout_s: float | None = None  # None: a limit that grows with the page count


@dataclass(frozen=True)
class DocumentResult:
    pdf: Path
    pages_read: int
    dropped: tuple[int, ...]  # 1-based numbers of the pages left out as blank
    pages_in_pdf: int
    ocr: OcrOutcome

    @property
    def ok(self) -> bool:
        return self.ocr.status not in (OcrStatus.FAILED, OcrStatus.TIMED_OUT)


def build_document(
    pages: Sequence[Path],
    settings: DocumentSettings,
    *,
    cancel: threading.Event | None = None,
    clock: Callable[[], datetime] | None = None,
) -> DocumentResult:
    """Make one PDF in ``settings.output_root`` from page files, in the order given.

    Every page file is checked first (nothing is written if one is unusable), then the pages
    are processed one at a time so only encoded bytes are kept. Input files are never touched.
    A failed or timed-out OCR still publishes the plain PDF (``result.ok`` is then False).
    """
    raise NotImplementedError
