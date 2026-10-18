"""Drafts made of numbers only (no files), to try the edits on."""

from collections.abc import Collection

from fastfoto_linux.documents.draft import DocumentDraft, PageAnalysis, TrimBox
from fastfoto_linux.documents.draft_edit import parts


def draft_of(
    count: int, *, blank: Collection[int] = (), keep_blank: bool = False, duplex: bool = False
) -> DocumentDraft:
    pages = tuple(
        PageAnalysis(
            number=n,
            name=f"page-{n:02d}.png",
            size=1,
            mtime_ns=1,
            dpi=100,
            trim=TrimBox(0, 0, 0, 0),
            blank=n in blank,
        )
        for n in range(1, count + 1)
    )
    return DocumentDraft(pages=pages, raw_dir=None, duplex=duplex, keep_blank=keep_blank)


def layout(draft: DocumentDraft) -> list[list[tuple[int, int]]]:
    """The parts as lists of (raw number, quarter turns), in output order."""
    return [[(page.number, turns) for page, turns in part.pages] for part in parts(draft)]


def numbers(draft: DocumentDraft) -> list[list[int]]:
    return [[n for n, _ in part] for part in layout(draft)]
