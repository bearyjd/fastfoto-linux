"""The scan form: what the user can set, checked field by field, turned into a ScanRequest."""

import os
from collections.abc import Callable
from dataclasses import dataclass, fields, replace
from pathlib import Path

from fastfoto_linux.cli.options import DEFAULT_DPI, FEED_FACE_DOWN, FEED_FACE_UP
from fastfoto_linux.enhance.orient import auto_orient
from fastfoto_linux.enhance.redeye import remove_red_eye
from fastfoto_linux.enhance.restore import restore_colour
from fastfoto_linux.output import DEFAULT_QUALITY, DateRange, PhotoDate
from fastfoto_linux.output.errors import InvalidAlbumError, InvalidDateError
from fastfoto_linux.output.metadata import MAX_NOTES_CHARS
from fastfoto_linux.output.naming import album_dir, default_prefix, sanitise_album
from fastfoto_linux.pipeline.process import Enhancer, ProcessSettings
from fastfoto_linux.pipeline.sides import BackPolicy
from fastfoto_linux.scanner import SUPPORTED_DPI, ScanTarget
from fastfoto_linux.session import RawPolicy, ScanRequest

FEED_CHOICES = (FEED_FACE_UP, FEED_FACE_DOWN)
BACK_CHOICES = tuple(policy.value for policy in BackPolicy)
NUMBER_PATTERN = "####"  # the real number is only known when the photo is written


@dataclass(frozen=True)
class ScanForm:
    """Every setting of the scan page, as the user typed it (text stays text until checked).

    The defaults are those of ``ffscan scan``.
    """

    output_folder: str = ""
    album: str = ""
    date: str = ""
    notes: str = ""
    loaded: str = FEED_FACE_UP
    backs: str = BackPolicy.AUTO.value
    restore: bool = True
    orient: bool = True
    redeye: bool = False
    dpi: int = DEFAULT_DPI
    keep_original: bool = True


FIELD_NAMES = tuple(field.name for field in fields(ScanForm))
_BOOL_FIELDS = frozenset(field.name for field in fields(ScanForm) if field.type is bool)


class FormInvalidError(ValueError):
    """The form has errors; ``errors`` maps each bad field to a message for the user."""

    def __init__(self, errors: dict[str, str]) -> None:
        super().__init__("; ".join(f"{name}: {message}" for name, message in errors.items()))
        self.errors = errors


def _expand(text: str) -> Path | None:
    """The path ``text`` names with ``~`` expanded; None when it is ``~name`` for no such user."""
    try:
        return Path(text.strip()).expanduser()
    except RuntimeError:
        return None


def _folder(form: ScanForm) -> Path:
    return _expand(form.output_folder) or Path(form.output_folder.strip())


def absolute_folder(text: str) -> str:
    """The output folder as a full path (``~`` expanded), empty when it is blank or relative."""
    path = _expand(text) if text.strip() else None
    return str(path) if path is not None and path.is_absolute() else ""


def _check_folder_text(form: ScanForm) -> str | None:
    if not form.output_folder.strip():
        return "Choose the folder the photos are saved in."
    if _expand(form.output_folder) is None:
        user = form.output_folder.strip().split("/")[0].removeprefix("~")
        whose = f"of {user!r}" if user else "of this user"
        return f"Cannot find the home folder {whose}; use a full path instead."
    if not _folder(form).is_absolute():
        return "Use a full path (one that starts with / or ~/), not a relative one."
    return None


def _check_folder_disk(form: ScanForm) -> str | None:
    folder = _folder(form)
    if not folder.exists():
        return f"The folder {folder} does not exist."
    if not folder.is_dir():
        return f"{folder} is not a folder."
    if not os.access(folder, os.W_OK | os.X_OK):
        return f"You cannot write to {folder}; choose a folder you can write to."
    return None


def _check_album_text(form: ScanForm) -> str | None:
    album = form.album.strip()
    if not album:
        return None
    try:
        sanitise_album(album)
    except InvalidAlbumError as error:
        return str(error)
    return None


def _check_album_disk(form: ScanForm) -> str | None:
    album = form.album.strip()
    if not album or _check_folder_disk(form) is not None:
        return None
    try:
        album_dir(_folder(form), album)
    except InvalidAlbumError as error:
        return str(error)
    return None


def _check_date(form: ScanForm) -> str | None:
    try:
        parse_date(form.date)
    except InvalidDateError as error:
        return str(error)
    return None


def _check_notes(form: ScanForm) -> str | None:
    if len(form.notes) > MAX_NOTES_CHARS:
        return f"Notes can be {MAX_NOTES_CHARS} characters at most; these are {len(form.notes)}."
    return None


def _choice(name: str, value: object, choices: tuple[object, ...]) -> str | None:
    if value in choices:
        return None
    return f"Unsupported {name} {value!r}; use one of {', '.join(map(str, choices))}."


_Check = Callable[[ScanForm], str | None]
_SYNTAX_CHECKS: tuple[tuple[str, _Check], ...] = (
    ("output_folder", _check_folder_text),
    ("album", _check_album_text),
    ("date", _check_date),
    ("notes", _check_notes),
    ("loaded", lambda form: _choice("loaded", form.loaded, FEED_CHOICES)),
    ("backs", lambda form: _choice("backs setting", form.backs, BACK_CHOICES)),
    ("dpi", lambda form: _choice("resolution", form.dpi, SUPPORTED_DPI)),
)
_DISK_CHECKS: tuple[tuple[str, _Check], ...] = (
    ("output_folder", _check_folder_disk),
    ("album", _check_album_disk),
)
_ORDER = tuple(name for name, _ in _SYNTAX_CHECKS)


def _run(checks: tuple[tuple[str, _Check], ...], form: ScanForm) -> dict[str, str]:
    results = ((name, check(form)) for name, check in checks)
    return {name: message for name, message in results if message is not None}


def validate_syntax(form: ScanForm) -> dict[str, str]:
    """A message per field whose text is wrong; looks at nothing but the form itself."""
    return _run(_SYNTAX_CHECKS, form)


DiskKey = tuple[str, str]
DiskCheck = Callable[[ScanForm], None]
"""Starts reading the disk for a form and returns at once; the answer goes to ``on_disk``."""


def disk_key(form: ScanForm) -> DiskKey:
    """What a read of the disk depends on: the output folder and the album."""
    return (form.output_folder.strip(), form.album.strip())


def validate_filesystem(form: ScanForm) -> dict[str, str]:
    """A message per field the disk disagrees with (a field whose text is bad is skipped)."""
    unreadable = validate_syntax(form).keys()
    return _run(tuple(check for check in _DISK_CHECKS if check[0] not in unreadable), form)


def merge_errors(*parts: dict[str, str]) -> dict[str, str]:
    """The messages of ``parts`` in form order, the first part's message winning for a field."""
    merged: dict[str, str] = {}
    for name in _ORDER:
        message = next((part[name] for part in parts if name in part), None)
        if message is not None:
            merged[name] = message
    return merged


def validate(form: ScanForm) -> dict[str, str]:
    """A message per bad field, empty when the form can be scanned (reads the disk)."""
    return merge_errors(validate_syntax(form), validate_filesystem(form))


def parse_date(text: str) -> PhotoDate | DateRange | None:
    """The date the text means (a year, month, day or a range), None when it is blank.

    Raises InvalidDateError for anything else. A range (``1970/1979``) goes beyond what
    ``ffscan scan --date`` accepts, but the processing settings take it.
    """
    stripped = text.strip()
    if not stripped:
        return None
    return DateRange.parse(stripped) if "/" in stripped else PhotoDate.parse(stripped)


def destination(form: ScanForm) -> str | None:
    """Where the photos will go and what they will be called, None when that is not known yet.

    The number is shown as ``####``: which numbers are free is up to the folder, and looking
    would read the disk on every keystroke.
    """
    if validate_syntax(form).keys() & {"output_folder", "album"}:
        return None
    album = form.album.strip() or None
    try:
        prefix = default_prefix(album)
        folder = _folder(form) if album is None else _folder(form) / sanitise_album(album)
    except InvalidAlbumError:
        return None
    return f"{folder}/{prefix}_{NUMBER_PATTERN}.jpg"


def update_field(form: ScanForm, name: str, value: object) -> ScanForm:
    """A copy of ``form`` with one field set from a UI value (text, number or switch)."""
    if name not in FIELD_NAMES:
        raise ValueError(f"the form has no field {name!r}")
    if name in _BOOL_FIELDS:
        return replace(form, **{name: bool(value)})
    if name == "dpi":
        return replace(form, dpi=whole_number(name, value))
    return replace(form, **{name: str(value)})


def whole_number(name: str, value: object) -> int:
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"{name} must be a whole number, got {value!r}")
    try:
        return int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a whole number, got {value!r}") from None


def to_settings(form: ScanForm) -> ProcessSettings:
    """The processing settings of a valid form (the same mapping as ``ffscan scan``)."""
    errors = validate(form)
    if errors:
        raise FormInvalidError(errors)
    enabled = ((form.restore, restore_colour), (form.redeye, remove_red_eye))
    enhancers: tuple[Enhancer, ...] = tuple(func for on, func in enabled if on)
    return ProcessSettings(
        output_root=_folder(form),
        album=form.album.strip() or None,
        date=parse_date(form.date),
        notes=form.notes or None,
        duplex=True,
        back_policy=BackPolicy(form.backs),
        expect_front_first=form.loaded == FEED_FACE_DOWN,
        quality=DEFAULT_QUALITY,
        keep_original=form.keep_original,
        enhancers=enhancers,
        orienter=auto_orient if form.orient else None,
    )


def to_request(form: ScanForm, target: ScanTarget) -> ScanRequest:
    """The scan request of a valid form for the scanner at ``target``."""
    return ScanRequest(
        target=target,
        dpi=form.dpi,
        duplex=True,
        settings=to_settings(form),
        raw_policy=RawPolicy.AUTO,
    )
