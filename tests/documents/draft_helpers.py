"""Drafts built by hand, and a counter of the pages that are decoded at the same time."""

import weakref
from collections.abc import Callable, Collection, Sequence
from pathlib import Path
from typing import Any

from fastfoto_linux.documents import DocumentSettings
from fastfoto_linux.documents.draft import DocumentDraft, PageAnalysis, TrimBox
from fastfoto_linux.documents.encode import encode_page
from fastfoto_linux.documents.loader import LoadedPage, load_page
from fastfoto_linux.documents.trim import trim_page


def hand_draft(
    pages: Sequence[Path],
    settings: DocumentSettings,
    *,
    blank: Collection[int] = (),
    with_bytes: bool = True,
) -> DocumentDraft:
    """The draft of ``pages`` with these (1-based) numbers judged blank, made without the
    analysis: the page encoded (when ``with_bytes``) from the trimmed pixels."""
    analyses = []
    for number, path in enumerate(pages, start=1):
        trimmed = trim_page(load_page(path, fallback_dpi=settings.fallback_dpi))
        first = number % 2 == 1
        partner = (number + 1 if first else number - 1) if settings.duplex else None
        if partner is not None and not 1 <= partner <= len(pages):
            partner = None
        kept = number not in blank or settings.keep_blank
        info = path.stat()
        analyses.append(
            PageAnalysis(
                number=number,
                name=path.name,
                size=info.st_size,
                mtime_ns=info.st_mtime_ns,
                dpi=trimmed.page.dpi,
                trim=TrimBox.from_trimmed(trimmed),
                blank=number in blank,
                partner=partner,
                encoded=encode_page(trimmed.page, settings.colour) if with_bytes and kept else None,
            )
        )
    return DocumentDraft(
        pages=tuple(analyses),
        raw_dir=pages[0].parent,
        duplex=settings.duplex,
        keep_blank=settings.keep_blank,
    )


class LiveCounter:
    """Stands in for ``load_page``: counts the pixel arrays it handed out that are still alive
    (a trimmed view keeps its array alive) and keeps the largest number seen at one time."""

    def __init__(self, after_load: Callable[[int], None] | None = None) -> None:
        self.after_load = after_load
        self.loads = 0
        self.peak = 0
        self._arrays: list[weakref.ref[Any]] = []

    def __call__(self, path: Path, **kwargs: Any) -> LoadedPage:
        page = load_page(path, **kwargs)
        self.loads += 1
        self._arrays.append(weakref.ref(page.pixels))
        self.peak = max(self.peak, sum(ref() is not None for ref in self._arrays))
        if self.after_load is not None:
            self.after_load(self.loads)
        return page
