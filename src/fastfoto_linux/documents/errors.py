"""Exceptions raised by the documents-to-PDF package."""

from fastfoto_linux.output.errors import OutputRootMissingError


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


class DocumentSettingsError(DocumentError, ValueError):
    """The settings cannot be used (the name, the OCR languages, the output folder): nothing was
    scanned or written."""


class OutputFolderMissingError(DocumentSettingsError, OutputRootMissingError):
    """The output folder is not an existing folder: one error, whichever entry point finds it.

    It is a settings error (what a front end catches, and shows as it is) and still the
    ``OutputRootMissingError`` that the photo writer raises for the same condition.
    """
