"""Fakes for the Documents-mode GUI tests: results, a scripted session, a recording worker."""

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastfoto_linux.documents import DocumentResult, OcrOutcome, OcrStatus, PartResult
from fastfoto_linux.gui.docform import DocumentForm
from fastfoto_linux.session import DocumentRawReason, DocumentSessionResult, Stage
from tests.gui.helpers import FakeWorker, RecordingSink

PDF_NAME = "Document_0001.pdf"


def document(
    out: Path,
    *,
    pages: int = 3,
    dropped: tuple[int, ...] = (),
    ocr: OcrStatus = OcrStatus.DONE,
    detail: str = "",
) -> DocumentResult:
    return DocumentResult(
        pages_read=pages + len(dropped),
        dropped=dropped,
        parts=(PartResult(out / PDF_NAME, "Document", pages, OcrOutcome(ocr, detail)),),
    )


def pages_in(raw: Path, count: int = 3) -> tuple[Path, ...]:
    return tuple(raw / f"page-{number:04d}.png" for number in range(1, count + 1))


def clean_document(out: Path, **options: Any) -> DocumentSessionResult:
    made = document(out, **options)
    return DocumentSessionResult(document=made, pages_scanned=made.pages_read)


def cancelled_document(raw: Path, pages: int = 3) -> DocumentSessionResult:
    """What a cancel leaves: the pages scanned so far, no PDF."""
    return DocumentSessionResult(
        pages_scanned=pages,
        raw_dir=raw,
        raw_reason=DocumentRawReason.CANCELLED,
        cancelled=True,
        kept_pages=pages_in(raw, pages),
    )


def stopped_document(raw: Path, error: Exception, pages: int = 2) -> DocumentSessionResult:
    """What a scanner that fails part-way leaves: the finished pages, no PDF, the error."""
    return DocumentSessionResult(
        pages_scanned=pages,
        raw_dir=raw,
        raw_reason=DocumentRawReason.SCAN_ERROR,
        error=error,
        kept_pages=pages_in(raw, pages),
    )


@dataclass
class DocFakeWorker(FakeWorker):
    """A FakeWorker that also records the document calls."""

    def scan_documents(
        self,
        form: DocumentForm,
        folder: str,
        *,
        ocr_available: bool,
        checked: bool = False,
        review: bool = False,
    ) -> None:
        self.review = review
        self.calls.append(("scan_documents", (form, folder, ocr_available, checked)))


class DocRecordingSink(RecordingSink):
    def on_build_page(self, progress: tuple[int, int]) -> None:
        self._add("build_page", progress)

    def on_ocr(self, _: object = None) -> None:
        self._add("ocr")

    def on_review_deskew(self, answer: object) -> None:
        self._add("review_deskew", answer)


class ScriptedDocumentSession:
    """Stands in for run_document_session: plays one document scan for the UI tests.

    It reports its stages, pages and the PDF's progress like the real session (through the
    ``build`` it is given), and with ``hold`` waits in the SCANNING stage until ``release`` is set
    or the cancel event is (then it returns the pages as kept, as a cancel during the scan does).
    """

    def __init__(
        self,
        out: Path,
        *,
        pages: int = 3,
        hold: bool = False,
        result: DocumentSessionResult | None = None,
        raises: Exception | None = None,
    ) -> None:
        self.out = out
        self.pages = pages
        self.hold = hold
        self.result = result
        self.raises = raises
        self.release = threading.Event()
        self.holding = threading.Event()
        self.requests: list[Any] = []
        self.hooks: list[dict[str, Any]] = []

    def __call__(self, request: Any, **hooks: Any) -> DocumentSessionResult:
        self.requests.append(request)
        self.hooks.append(hooks)
        if self.raises is not None:
            raise self.raises
        hooks["on_stage"](Stage.CHECKING)
        hooks["on_stage"](Stage.SCANNING)
        for number in range(1, self.pages + 1):
            hooks["on_page"](number)
        if self.hold:
            self.holding.set()
            cancel = hooks["cancel"]
            while not (self.release.is_set() or cancel.is_set()):
                cancel.wait(0.005)
            if cancel.is_set():
                return cancelled_document(self.out / ".raw" / "stamp", self.pages)
        hooks["on_stage"](Stage.PROCESSING)
        made = hooks["build"](
            pages_in(self.out / ".raw" / "stamp", self.pages),
            request.settings,
            cancel=hooks["cancel"],
        )
        hooks["on_stage"](Stage.DONE)
        return self.result or DocumentSessionResult(document=made, pages_scanned=self.pages)


class FakeBuild:
    """Stands in for build_document: reports each page and the OCR like the real one."""

    def __init__(self, out: Path, *, ocr: bool = True, fail: Exception | None = None) -> None:
        self.out = out
        self.ocr = ocr
        self.fail = fail
        self.calls: list[tuple[tuple[Path, ...], Any]] = []
        self.hold = threading.Event()

    def __call__(
        self,
        pages: Any,
        settings: Any,
        *,
        cancel: threading.Event | None = None,
        on_page: Any = None,
        on_ocr: Any = None,
        **_: Any,
    ) -> DocumentResult:
        self.calls.append((tuple(pages), settings))
        if self.fail is not None:
            raise self.fail
        for number in range(1, len(pages) + 1):
            if on_page is not None:
                on_page(number, len(pages))
        if self.ocr and on_ocr is not None:
            on_ocr()
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / PDF_NAME).write_bytes(b"%PDF-1.7\n")
        return document(self.out, pages=len(pages))


__all__ = [
    "DocFakeWorker",
    "DocRecordingSink",
    "FakeBuild",
    "ScriptedDocumentSession",
    "cancelled_document",
    "clean_document",
    "document",
    "pages_in",
    "stopped_document",
]
