"""The scan form: what the user can set, checked field by field, turned into a ScanRequest."""

from dataclasses import dataclass, fields

from fastfoto_linux.cli.options import DEFAULT_DPI, FEED_FACE_DOWN, FEED_FACE_UP
from fastfoto_linux.output import DateRange, PhotoDate
from fastfoto_linux.pipeline.process import ProcessSettings
from fastfoto_linux.pipeline.sides import BackPolicy
from fastfoto_linux.scanner import ScanTarget
from fastfoto_linux.session import ScanRequest

FEED_CHOICES = (FEED_FACE_DOWN, FEED_FACE_UP)
BACK_CHOICES = tuple(policy.value for policy in BackPolicy)


@dataclass(frozen=True)
class ScanForm:
    """Every setting of the scan page, as the user typed it (text stays text until checked).

    The defaults are those of ``ffscan scan``.
    """

    output_folder: str = ""
    album: str = ""
    date: str = ""
    notes: str = ""
    feed: str = FEED_FACE_DOWN
    backs: str = BackPolicy.AUTO.value
    restore: bool = True
    orient: bool = True
    redeye: bool = False
    dpi: int = DEFAULT_DPI
    keep_original: bool = True


FIELD_NAMES = tuple(field.name for field in fields(ScanForm))


class FormInvalidError(ValueError):
    """The form has errors; ``errors`` maps each bad field to a message for the user."""

    def __init__(self, errors: dict[str, str]) -> None:
        super().__init__("; ".join(f"{name}: {message}" for name, message in errors.items()))
        self.errors = errors


def validate(form: ScanForm) -> dict[str, str]:
    """A message per bad field, empty when the form can be scanned."""
    raise NotImplementedError


def parse_date(text: str) -> PhotoDate | DateRange | None:
    """The date the text means (a year, month, day or a range), None when it is blank."""
    raise NotImplementedError


def destination(form: ScanForm) -> str | None:
    """Where the photos will go and what they will be called, None when that is not known yet."""
    raise NotImplementedError


def update_field(form: ScanForm, name: str, value: object) -> ScanForm:
    """A copy of ``form`` with one field set from a UI value (text, number or switch)."""
    raise NotImplementedError


def to_settings(form: ScanForm) -> ProcessSettings:
    """The processing settings of a valid form."""
    raise NotImplementedError


def to_request(form: ScanForm, target: ScanTarget) -> ScanRequest:
    """The scan request of a valid form for the scanner at ``target``."""
    raise NotImplementedError
