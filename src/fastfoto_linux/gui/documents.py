"""A PDF as the results list shows it."""

from dataclasses import dataclass
from pathlib import Path

from fastfoto_linux.documents import DocumentResult, OcrStatus


@dataclass(frozen=True)
class DocumentItem:
    """One PDF made: its file, the pages in it, the blank pages left out and how the OCR went."""

    pdf: Path
    pages: int
    dropped: tuple[int, ...]
    ocr: OcrStatus
    ocr_detail: str = ""

    @property
    def file_name(self) -> str:
        raise NotImplementedError

    @property
    def folder(self) -> Path:
        raise NotImplementedError

    @property
    def pages_text(self) -> str:
        raise NotImplementedError

    @property
    def dropped_text(self) -> str:
        raise NotImplementedError

    @property
    def searchable_text(self) -> str:
        raise NotImplementedError

    @property
    def ocr_warning(self) -> bool:
        raise NotImplementedError


def item_from_document(result: DocumentResult) -> DocumentItem:
    raise NotImplementedError
