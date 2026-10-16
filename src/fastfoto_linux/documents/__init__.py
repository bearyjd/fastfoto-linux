"""Scanned paper documents to one searchable PDF."""

from fastfoto_linux.documents.build import (
    DEFAULT_NAME,
    DocumentResult,
    DocumentSettings,
    build_document,
    check_settings,
)
from fastfoto_linux.documents.errors import (
    AllPagesBlankError,
    DocumentCancelledError,
    DocumentError,
    DocumentSettingsError,
    OcrCancelledError,
    OcrMissingError,
    UnsupportedPageError,
)
from fastfoto_linux.documents.modes import ColourMode
from fastfoto_linux.documents.ocr import (
    DEFAULT_LANGS,
    OcrMode,
    OcrOutcome,
    OcrStatus,
    find_ocrmypdf,
    validate_langs,
)

__all__ = [
    "DEFAULT_LANGS",
    "DEFAULT_NAME",
    "AllPagesBlankError",
    "ColourMode",
    "DocumentCancelledError",
    "DocumentError",
    "DocumentResult",
    "DocumentSettings",
    "DocumentSettingsError",
    "OcrCancelledError",
    "OcrMissingError",
    "OcrMode",
    "OcrOutcome",
    "OcrStatus",
    "UnsupportedPageError",
    "build_document",
    "check_settings",
    "find_ocrmypdf",
    "validate_langs",
]
