"""The paper cleanup fields of the review sidecar, version 3 (the reading is in ``draft_json``)."""

from typing import Any

from fastfoto_linux.documents.draft import DocumentDraft, PageEdit
from fastfoto_linux.documents.modes import CleanupPolicy

EDIT_KEYS = frozenset({"include", "turns", "colour", "cleanup"})  # exactly these, in version 3


def uses_cleanup(draft: DocumentDraft) -> bool:
    """Whether the draft holds paper cleanup state, so only version 3 can hold it."""
    return draft.cleanup is not CleanupPolicy.OFF or any(
        edit.cleanup is not None for edit in draft.edits.values()
    )


def edit_json(edit: PageEdit, *, with_cleanup: bool) -> dict[str, Any]:
    data: dict[str, Any] = {
        "include": edit.include,
        "turns": edit.quarter_turns,
        "colour": None if edit.colour is None else edit.colour.value,
    }
    if with_cleanup:
        data["cleanup"] = None if edit.cleanup is None else edit.cleanup.value
    return data
