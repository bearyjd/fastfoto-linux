"""Run one document scan session: scan into a raw folder, make the PDF, settle the raw pages."""

import threading
from collections.abc import Callable

from fastfoto_linux.scanner import run_scan  # noqa: F401 - used by the implementation
from fastfoto_linux.scanner.precheck import check_scanner  # noqa: F401 - used by the implementation
from fastfoto_linux.session.raw import settle_raw_dir  # noqa: F401 - used by the implementation
from fastfoto_linux.session.request import DocumentScanRequest
from fastfoto_linux.session.result import DocumentSessionResult, Stage


def run_document_session(  # noqa: PLR0913
    request: DocumentScanRequest,
    *,
    on_page: Callable[[int], None] | None = None,
    on_stage: Callable[[Stage], None] | None = None,
    cancel: threading.Event | None = None,
    scan: Callable[..., object] | None = None,
    build: Callable[..., object] | None = None,
    precheck: Callable[..., None] | None = None,
) -> DocumentSessionResult:
    """Scan the document feeder, make the PDF and settle the raw pages."""
    raise NotImplementedError
