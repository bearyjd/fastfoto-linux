"""Turn page files into one PDF: analyse the pages, then write the PDF.

Order of work, and why:

1. Everything that can be refused is refused before any page is processed: the settings
   (``check_settings``: the name, the languages, a required ``ocrmypdf`` that is missing, which
   a scan session checks too before it scans) and every page file (header and a full decode, so
   a truncated PNG is found now and not after ten pages of work). Nothing is written when a
   page is unusable, because a PDF with a page silently missing is worse than no PDF.
2. ``analyse`` then works on the pages a sheet at a time (two pages of a duplex document, one
   otherwise: a hole through the paper is told from a mark by the sheet's other side) and keeps
   only a verdict, a trim box and the encoded bytes of each page; a cancel is honoured before
   each page, in the checks as well as in the processing.
3. ``write`` puts the pages that stay in one PDF. The OCR runs on the finished plain PDF
   *before* the output folder is locked (it can take minutes; the lock is for numbering and
   writing only), and a failed or timed-out OCR falls back to publishing the plain PDF.
"""

import threading
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

from fastfoto_linux.documents.analyse import analyse_document
from fastfoto_linux.documents.settings import DocumentSettings
from fastfoto_linux.documents.write import DocumentResult, write_document


def build_document(  # noqa: PLR0913 - the hooks are the interface
    pages: Sequence[Path],
    settings: DocumentSettings,
    *,
    cancel: threading.Event | None = None,
    clock: Callable[[], datetime] | None = None,
    on_page: Callable[[int, int], None] | None = None,
    on_ocr: Callable[[], None] | None = None,
) -> DocumentResult:
    """Make one PDF in ``settings.output_root`` from page files, in the order given.

    Every page file is checked first (nothing is written if one is unusable), then the pages
    are processed a sheet at a time so only encoded bytes are kept. With ``settings.duplex`` the
    pages are the two sides of sheets in order, (1, 2), (3, 4) ..., and a mark on a page that is
    a hole through the paper, also on its sheet's other side, is not a mark (see ``holes``).
    Input files are never touched.
    A failed or timed-out OCR still publishes the plain PDF (``result.ok`` is then False).
    When ``cancel`` is set DocumentCancelledError (OcrCancelledError during OCR) is raised and
    nothing is published. Settings that cannot make a PDF are refused first (``check_settings``).

    ``on_page(number, total)`` is called before each page is processed (a page that is then dropped
    as blank included) and ``on_ocr()`` once before the searchable text is made, so that a front
    end can say where the work is. Both run on the calling thread.
    """
    draft = analyse_document(pages, settings, cancel=cancel, on_page=on_page)
    return write_document(draft, settings, cancel=cancel, clock=clock, on_ocr=on_ocr)
