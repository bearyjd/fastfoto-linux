"""Scanned paper documents to one searchable PDF."""

from fastfoto_linux.documents.build import build_document
from fastfoto_linux.documents.errors import (
    AllPagesBlankError,
    DocumentCancelledError,
    DocumentError,
    DocumentSettingsError,
    NothingSelectedError,
    OcrCancelledError,
    OcrMissingError,
    OutputFolderMissingError,
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
from fastfoto_linux.documents.settings import DEFAULT_NAME, DocumentSettings, check_settings
from fastfoto_linux.documents.write import DocumentResult, PartResult

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
    "NothingSelectedError",
    "OcrCancelledError",
    "OcrMissingError",
    "OcrMode",
    "OcrOutcome",
    "OcrStatus",
    "OutputFolderMissingError",
    "PartResult",
    "UnsupportedPageError",
    "build_document",
    "check_settings",
    "find_ocrmypdf",
    "validate_langs",
]
