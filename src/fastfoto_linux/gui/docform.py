"""The Documents form: what the user can set, checked field by field, turned into a request."""

from dataclasses import dataclass, fields
from pathlib import Path

from fastfoto_linux.documents import DEFAULT_LANGS, ColourMode, DocumentSettings, OcrMode
from fastfoto_linux.scanner import ScanTarget
from fastfoto_linux.session import DEFAULT_DOCUMENT_DPI, DocumentScanRequest

DOCUMENT_COLOURS = tuple(mode.value for mode in ColourMode)


@dataclass(frozen=True)
class DocumentForm:
    """Every setting of Documents mode, as the user typed it. The defaults are those of
    ``ffscan doc scan``; the output folder is the Photos form's (one folder for both modes)."""

    name: str = ""
    colour: str = ColourMode.COLOUR.value
    dpi: int = DEFAULT_DOCUMENT_DPI
    both_sides: bool = True
    keep_blank: bool = False
    searchable: bool = True
    langs: str = DEFAULT_LANGS


DOCUMENT_FIELD_NAMES = tuple(field.name for field in fields(DocumentForm))


def validate_document_form(form: DocumentForm) -> dict[str, str]:
    raise NotImplementedError


def document_errors(form: DocumentForm, folder: str, *, disk: bool) -> dict[str, str]:
    raise NotImplementedError


def update_document_field(form: DocumentForm, name: str, value: object) -> DocumentForm:
    raise NotImplementedError


def ocr_mode(form: DocumentForm, *, ocr_available: bool) -> OcrMode:
    raise NotImplementedError


def to_document_settings(
    form: DocumentForm, output_root: Path, *, ocr_available: bool
) -> DocumentSettings:
    raise NotImplementedError


def to_document_request(
    form: DocumentForm, folder: str, target: ScanTarget, *, ocr_available: bool
) -> DocumentScanRequest:
    raise NotImplementedError


def document_destination(form: DocumentForm, folder: str) -> str | None:
    raise NotImplementedError
