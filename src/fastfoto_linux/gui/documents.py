"""A PDF as the results list shows it."""

from dataclasses import dataclass
from pathlib import Path

from fastfoto_linux.documents import DocumentResult, OcrStatus
from fastfoto_linux.documents.ocr_tools import OCR_UNAVAILABLE_TEXT
from fastfoto_linux.gui.report import count_noun

_OCR_PROBLEMS = (OcrStatus.FAILED, OcrStatus.TIMED_OUT)
_SEARCHABLE_LINES = {
    OcrStatus.DONE: "Searchable text: yes",
    OcrStatus.SKIPPED: "Searchable text: no (turned off)",
}


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
        return self.pdf.name

    @property
    def folder(self) -> Path:
        return self.pdf.parent

    @property
    def pages_text(self) -> str:
        return count_noun(self.pages, "page")

    @property
    def dropped_text(self) -> str:
        """The blank pages left out, by number ("Blank pages left out: 2, 4"), or empty."""
        if not self.dropped:
            return ""
        noun = "page" if len(self.dropped) == 1 else "pages"
        return f"Blank {noun} left out: {', '.join(map(str, self.dropped))}"

    @property
    def ocr_warning(self) -> bool:
        """True when searchable text was wanted and could not be added."""
        return self.ocr in _OCR_PROBLEMS

    @property
    def searchable_text(self) -> str:
        """Whether the PDF has searchable text, and if not why (the CLI's words)."""
        if self.ocr_warning:
            reason = self.ocr_detail or self.ocr.value
            return f"Searchable text could not be added ({reason}); the plain PDF was saved instead"
        if self.ocr is OcrStatus.UNAVAILABLE:  # the detail names what is missing
            return f"Searchable text: no ({self.ocr_detail or OCR_UNAVAILABLE_TEXT})"
        return _SEARCHABLE_LINES[self.ocr]


def item_from_document(result: DocumentResult) -> DocumentItem:
    return DocumentItem(
        pdf=result.pdf,
        pages=result.pages_in_pdf,
        dropped=result.dropped,
        ocr=result.ocr.status,
        ocr_detail=result.ocr.detail,
    )


def items_from_document(result: DocumentResult) -> tuple[DocumentItem, ...]:
    raise NotImplementedError
