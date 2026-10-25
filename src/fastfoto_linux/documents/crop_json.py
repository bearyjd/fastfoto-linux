"""The crop field of the review sidecar, version 4 (the reading is in ``draft_json``)."""

from typing import Any

from fastfoto_linux.documents.cleanup_json import EDIT_KEYS
from fastfoto_linux.documents.draft import DocumentDraft
from fastfoto_linux.documents.page_crop import PageCrop

CROP_EDIT_KEYS = EDIT_KEYS | {"crop"}  # exactly these, in version 4
CROP_SIDES = 4  # left, top, right, bottom


class CropFormatError(ValueError):
    """A stored crop is not usable; ``draft_json`` raises its ReviewFormatError for it."""


def uses_crop(draft: DocumentDraft) -> bool:
    """Whether a page of the draft is cropped, so only version 4 can hold it."""
    return any(edit.crop is not None for edit in draft.edits.values())


def crop_json(crop: PageCrop | None) -> list[int] | None:
    return None if crop is None else [crop.left, crop.top, crop.right, crop.bottom]


def parse_crop(value: Any, what: str) -> PageCrop | None:
    """The crop stored as ``value``: None, or four whole numbers [left, top, right, bottom]
    that ``PageCrop`` accepts (whole units enclosing an area). Else CropFormatError."""
    if value is None:
        return None
    if type(value) is not list or len(value) != CROP_SIDES:
        raise CropFormatError(f"{what} must be null or a list of four numbers")
    try:
        return PageCrop(*value)
    except ValueError as error:
        raise CropFormatError(
            f"{what} must be whole numbers from 0 to 10000 that enclose an area"
        ) from error
