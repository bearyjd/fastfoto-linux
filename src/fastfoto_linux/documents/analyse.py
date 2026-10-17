"""Analyse a document: check every page, then judge and encode them a sheet at a time."""

import threading
from collections.abc import Callable, Sequence
from pathlib import Path

from fastfoto_linux.documents.build import DocumentSettings
from fastfoto_linux.documents.draft import DocumentDraft
from fastfoto_linux.documents.loader import load_page  # noqa: F401 - stub until the analysis exists


def analyse_document(
    pages: Sequence[Path],
    settings: DocumentSettings,
    *,
    cancel: threading.Event | None = None,
    on_page: Callable[[int, int], None] | None = None,
    encode: bool = True,
) -> DocumentDraft:
    raise NotImplementedError
