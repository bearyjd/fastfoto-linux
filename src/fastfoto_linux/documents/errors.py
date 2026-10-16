"""Exceptions raised by the documents-to-PDF package."""


class DocumentError(Exception):
    """Base class for every documents failure that ends a run with one clear message."""


class UnsupportedPageError(DocumentError):
    """A page file cannot be used: not a PNG, an unsupported mode, no usable resolution."""


class AllPagesBlankError(DocumentError):
    """Every page looked blank, so there is nothing to put in a PDF."""


class OcrMissingError(DocumentError):
    """Searchable text was required (``--ocr on``) but ``ocrmypdf`` is not installed."""


class DocumentCancelledError(DocumentError):
    """The caller asked to stop while pages were being processed; nothing was written."""


class OcrCancelledError(DocumentCancelledError):
    """The caller asked to stop while OCR was running; the OCR process is gone."""
