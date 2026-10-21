"""The Documents form: what the user can set, checked field by field, turned into a request."""

from dataclasses import dataclass, fields, replace
from pathlib import Path

from fastfoto_linux.documents import (
    DEFAULT_LANGS,
    DEFAULT_NAME,
    CleanupPolicy,
    ColourPolicy,
    DocumentSettings,
    OcrMode,
    validate_langs,
)
from fastfoto_linux.gui.form import (
    NUMBER_PATTERN,
    FormInvalidError,
    ScanForm,
    validate,
    validate_syntax,
    whole_number,
)
from fastfoto_linux.output.errors import InvalidPrefixError
from fastfoto_linux.output.naming import sanitise_prefix
from fastfoto_linux.scanner import ScanTarget
from fastfoto_linux.session import (
    DEFAULT_DOCUMENT_DPI,
    DOCUMENT_DPI,
    DocumentScanRequest,
    RawPolicy,
)

DOCUMENT_COLOURS = tuple(mode.value for mode in ColourPolicy)
DOCUMENT_CLEANUPS = tuple(policy.value for policy in CleanupPolicy)
FOLDER_FIELD = "output_folder"


@dataclass(frozen=True)
class DocumentForm:
    """Every setting of Documents mode, as the user typed it. The defaults are those of
    ``ffscan doc scan``; the output folder is the Photos form's (one folder for both modes)."""

    name: str = ""
    colour: str = ColourPolicy.COLOUR.value
    dpi: int = DEFAULT_DOCUMENT_DPI
    both_sides: bool = True
    keep_blank: bool = False
    searchable: bool = True
    langs: str = DEFAULT_LANGS
    cleanup: str = CleanupPolicy.OFF.value


DOCUMENT_FIELD_NAMES = tuple(field.name for field in fields(DocumentForm))
_BOOL_FIELDS = frozenset(field.name for field in fields(DocumentForm) if field.type is bool)


def _check_name(form: DocumentForm) -> str | None:
    """A blank name means the default name; anything else must leave a usable file name."""
    if not form.name.strip():
        return None
    try:
        sanitise_prefix(form.name)
    except InvalidPrefixError:
        return "The name has no characters that can be used in a file name."
    return None


def _check_langs(form: DocumentForm) -> str | None:
    try:
        validate_langs(form.langs)
    except ValueError as error:
        return str(error)
    return None


def _choice(name: str, value: object, choices: tuple[object, ...]) -> str | None:
    if value in choices:
        return None
    return f"Unsupported {name} {value!r}; use one of {', '.join(map(str, choices))}."


def validate_document_form(form: DocumentForm) -> dict[str, str]:
    """A message per field whose value is wrong, in form order (the same rules as the CLI)."""
    checks = (
        ("name", _check_name(form)),
        ("colour", _choice("colour", form.colour, DOCUMENT_COLOURS)),
        ("dpi", _choice("resolution", form.dpi, DOCUMENT_DPI)),
        ("cleanup", _choice("paper cleanup", form.cleanup, DOCUMENT_CLEANUPS)),
        ("langs", _check_langs(form)),
    )
    return {name: message for name, message in checks if message is not None}


def folder_errors(folder: str, *, disk: bool) -> dict[str, str]:
    """The message for the output folder alone (photo fields are not documents' business)."""
    probe = ScanForm(output_folder=folder)
    found = validate(probe) if disk else validate_syntax(probe)
    return {name: message for name, message in found.items() if name == FOLDER_FIELD}


def document_errors(form: DocumentForm, folder: str, *, disk: bool) -> dict[str, str]:
    """The folder's message, if any, then the form's: empty when a scan can start."""
    return {**folder_errors(folder, disk=disk), **validate_document_form(form)}


def update_document_field(form: DocumentForm, name: str, value: object) -> DocumentForm:
    """A copy of ``form`` with one field set from a UI value (text, number or switch)."""
    if name not in DOCUMENT_FIELD_NAMES:
        raise ValueError(f"the documents form has no field {name!r}")
    if name in _BOOL_FIELDS:
        return replace(form, **{name: bool(value)})
    if name == "dpi":
        return replace(form, dpi=whole_number(name, value))
    return replace(form, **{name: str(value)})


def ocr_mode(form: DocumentForm, *, ocr_available: bool) -> OcrMode:
    """Searchable text is asked for (and then required) only when wanted and installed.

    ON, not AUTO, when it is wanted: a tool that vanished since the form was drawn is refused
    before the stack is scanned, not found missing after it. Where it cannot be had, the form
    has the box disabled, and the PDF is made without.
    """
    return OcrMode.ON if form.searchable and ocr_available else OcrMode.OFF


def to_document_settings(
    form: DocumentForm, output_root: Path, *, ocr_available: bool
) -> DocumentSettings:
    """The PDF settings of a form (a blank name is the default name)."""
    return DocumentSettings(
        output_root=output_root,
        name=form.name.strip() or DEFAULT_NAME,
        colour=ColourPolicy(form.colour),
        keep_blank=form.keep_blank,
        ocr=ocr_mode(form, ocr_available=ocr_available),
        langs=form.langs,
        duplex=form.both_sides,
        cleanup=CleanupPolicy(form.cleanup),
    )


def to_document_request(
    form: DocumentForm,
    folder: str,
    target: ScanTarget,
    *,
    ocr_available: bool,
    check_disk: bool = True,
) -> DocumentScanRequest:
    """The scan request of a valid form for the scanner at ``target``.

    Raises FormInvalidError for a bad form. ``check_disk=False`` leaves the folder's existence to
    the session, which refuses a missing one before anything is scanned.
    """
    errors = document_errors(form, folder, disk=check_disk)
    if errors:
        raise FormInvalidError(errors)
    root = Path(folder.strip()).expanduser()
    return DocumentScanRequest(
        target=target,
        settings=to_document_settings(form, root, ocr_available=ocr_available),
        dpi=form.dpi,
        duplex=form.both_sides,
        raw_policy=RawPolicy.AUTO,
    )


def document_destination(form: DocumentForm, folder: str) -> str | None:
    """Where the PDF will go and what it will be called, None while that is not known.

    The number is shown as ``####``: which numbers are free is up to the folder, and looking
    would read the disk on every keystroke.
    """
    if document_errors(form, folder, disk=False):
        return None
    prefix = sanitise_prefix(form.name.strip() or DEFAULT_NAME)
    return f"{Path(folder.strip()).expanduser()}/{prefix}_{NUMBER_PATTERN}.pdf"
