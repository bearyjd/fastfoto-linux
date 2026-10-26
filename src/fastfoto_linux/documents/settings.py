"""What a document is made with, and the refusal of settings that cannot make a PDF."""

from dataclasses import dataclass
from pathlib import Path

from fastfoto_linux.documents.errors import DocumentSettingsError, OcrMissingError
from fastfoto_linux.documents.modes import CleanupPolicy, ColourMode, ColourPolicy
from fastfoto_linux.documents.ocr import (
    DEFAULT_LANGS,
    OcrMode,
    find_ocrmypdf,
    validate_langs,
)
from fastfoto_linux.documents.ocr_tools import ocr_missing_text
from fastfoto_linux.documents.publish import require_output_folder
from fastfoto_linux.output.errors import InvalidPrefixError
from fastfoto_linux.output.naming import sanitise_prefix

DEFAULT_NAME = "Document"


@dataclass(frozen=True)
class DocumentSettings:
    output_root: Path
    name: str = DEFAULT_NAME
    colour: ColourPolicy | ColourMode = ColourMode.COLOUR
    keep_blank: bool = False
    ocr: OcrMode = OcrMode.AUTO
    langs: str = DEFAULT_LANGS
    fallback_dpi: int | None = None
    ocr_timeout_s: float | None = None  # None: a limit that grows with the page count
    duplex: bool = True  # pages are sheets' sides in order, (1, 2), (3, 4) ...; False: all fronts
    cleanup: CleanupPolicy = CleanupPolicy.OFF  # paper cleanup a new analysis starts with
    despeckle: bool = False  # remove small isolated specks from black and white pages


@dataclass(frozen=True)
class CheckedSettings:
    """What ``check_settings`` found out: the file name stem and the OCR tool to run, if any."""

    name: str
    ocr_executable: str | None


def check_settings(settings: DocumentSettings) -> CheckedSettings:
    """Refuse settings that cannot make a PDF, before any page is scanned or read.

    Raises DocumentSettingsError for a name with no usable characters or OCR languages that are
    no Tesseract codes (even with OCR off), and OcrMissingError when searchable text is required
    (``OcrMode.ON``) and OCR is not available (OCRmyPDF, Tesseract or both is missing), and
    ``OutputFolderMissingError`` (a DocumentSettingsError) when the output folder is not an
    existing folder: the caller makes it, and a PDF is not worked on, nor a stack of paper
    scanned, for a folder that is not there.
    """
    try:
        name = sanitise_prefix(settings.name)
    except InvalidPrefixError as error:
        raise DocumentSettingsError(
            f"the name {settings.name!r} has no usable characters for a file name"
        ) from error
    try:
        ColourPolicy(settings.colour)
    except (TypeError, ValueError) as error:
        raise DocumentSettingsError("colour mode must be auto, colour, grey or bw") from error
    if not isinstance(settings.cleanup, CleanupPolicy):
        raise DocumentSettingsError("cleanup must be off, light or strong")
    if type(settings.despeckle) is not bool:
        raise DocumentSettingsError("despeckle must be true or false")
    try:
        validate_langs(settings.langs)
    except ValueError as error:
        raise DocumentSettingsError(str(error)) from error
    executable = _ocr_executable(settings.ocr)
    require_output_folder(settings.output_root)
    return CheckedSettings(name, executable)


def _ocr_executable(mode: OcrMode) -> str | None:
    """The tool to run, or None when OCR is off or (``auto``) not available."""
    if mode is OcrMode.OFF:
        return None
    found = find_ocrmypdf()
    if found is None and mode is OcrMode.ON:
        raise OcrMissingError(f"searchable text needs OCR, but {ocr_missing_text()}")
    return found
