"""The despeckle field of the review sidecar, version 5 (the reading is in ``draft_json``)."""

from fastfoto_linux.documents.draft import DocumentDraft


def uses_despeckle(draft: DocumentDraft) -> bool:
    """Whether the draft holds the despeckle switch, so only version 5 can hold it."""
    return draft.despeckle
