"""Whether a draft needs review sidecar format version 5 (``draft_json`` reads and writes it)."""

from fastfoto_linux.documents.draft import DocumentDraft


def uses_despeckle(draft: DocumentDraft) -> bool:
    """Whether the draft holds the despeckle switch, so only version 5 can hold it."""
    return draft.despeckle
