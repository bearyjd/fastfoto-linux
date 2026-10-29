"""The deskew field of the review sidecar, version 6 (the reading is in ``draft_json``)."""

from typing import Any

from fastfoto_linux.documents.crop_json import CROP_EDIT_KEYS
from fastfoto_linux.documents.deskew_tables import MAX_TENTHS
from fastfoto_linux.documents.draft import DocumentDraft

DESKEW_EDIT_KEYS = CROP_EDIT_KEYS | {"deskew"}  # exactly these, in version 6


class DeskewFormatError(ValueError):
    """A stored angle is not usable; ``draft_json`` raises its ReviewFormatError for it."""


def uses_deskew(draft: DocumentDraft) -> bool:
    """Whether a page of the draft has an angle, so only version 6 can hold it."""
    return any(edit.deskew_tenths is not None for edit in draft.edits.values())


def parse_deskew(value: Any, what: str) -> int | None:
    """The angle stored as ``value``: None, or a whole number of tenths of a degree from -100 to
    100 but not 0 (a bool, a float or a text is no angle). Else DeskewFormatError, which names
    ``what`` and never the value."""
    if value is None:
        return None
    if type(value) is not int or value == 0 or abs(value) > MAX_TENTHS:
        raise DeskewFormatError(
            f"{what} must be null or a whole number of tenths from -{MAX_TENTHS} to {MAX_TENTHS}, "
            "not 0"
        )
    return value
