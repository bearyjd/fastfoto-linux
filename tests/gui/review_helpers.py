"""Small synthetic document review fixtures."""

from pathlib import Path

from fastfoto_linux.documents.draft import DocumentDraft, Flag, PageAnalysis, TrimBox


def draft(folder: Path) -> DocumentDraft:
    pages = tuple(
        PageAnalysis(
            number=n,
            name=f"page-{n:04d}.png",
            size=10,
            mtime_ns=1,
            dpi=300,
            trim=TrimBox(0, 100, 0, 200, False),
            blank=n == 2,
            flags=frozenset({Flag.FEW_MARKS}) if n == 3 else frozenset(),
            thumb=f"page-{n:04d}.jpg",
        )
        for n in range(1, 4)
    )
    return DocumentDraft(pages, folder, duplex=True, keep_blank=False)
