"""A scan session: scan the feeder, process the pages and settle the raw pages, UI-neutral."""

from fastfoto_linux.session.documents import run_document_session
from fastfoto_linux.session.request import (
    DEFAULT_DOCUMENT_DPI,
    DOCUMENT_DPI,
    DocumentScanRequest,
    RawPolicy,
    ScanRequest,
)
from fastfoto_linux.session.result import (
    DocumentRawReason,
    DocumentSessionResult,
    RawReason,
    SessionResult,
    Stage,
)
from fastfoto_linux.session.run import run_session

__all__ = [
    "DEFAULT_DOCUMENT_DPI",
    "DOCUMENT_DPI",
    "DocumentRawReason",
    "DocumentScanRequest",
    "DocumentSessionResult",
    "RawPolicy",
    "RawReason",
    "ScanRequest",
    "SessionResult",
    "Stage",
    "run_document_session",
    "run_session",
]
