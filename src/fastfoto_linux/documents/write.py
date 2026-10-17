"""Write a document: assemble the PDF from an analysed draft, add searchable text, publish."""

import threading
from collections.abc import Callable
from datetime import datetime

from fastfoto_linux.documents.build import DocumentResult, DocumentSettings
from fastfoto_linux.documents.draft import DocumentDraft
from fastfoto_linux.documents.loader import load_page  # noqa: F401 - stub until the writer exists


def write_document(  # noqa: PLR0913 - the hooks are the interface
    draft: DocumentDraft,
    settings: DocumentSettings,
    *,
    cancel: threading.Event | None = None,
    clock: Callable[[], datetime] | None = None,
    on_page: Callable[[int, int], None] | None = None,
    on_ocr: Callable[[], None] | None = None,
) -> DocumentResult:
    raise NotImplementedError
