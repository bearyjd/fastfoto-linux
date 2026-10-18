"""Documents mode on the scan page: its form, its searchable-text tool, its progress and words."""

from fastfoto_linux.gui.docform import (
    FOLDER_FIELD,
    document_destination,
    update_document_field,
    validate_document_form,
)
from fastfoto_linux.gui.docreport import (
    document_error_banner,
    document_kept_text,
    document_progress_text,
    document_result_banner,
    offers_kept,
)
from fastfoto_linux.gui.doctools import DocumentSetup
from fastfoto_linux.gui.documents import DocumentItem, items_from_document
from fastfoto_linux.gui.form import ScanForm
from fastfoto_linux.gui.modes import CLOSE_SCAN_TEXT, CLOSE_SCAN_TITLE, WorkerPort
from fastfoto_linux.gui.report import Banner
from fastfoto_linux.gui.state import Mode, State
from fastfoto_linux.session import DocumentSessionResult

CLOSE_PDF_TITLE = "Cancel making the PDF?"
CLOSE_PDF_TEXT = (
    "The PDF is being made. If you cancel, no PDF is saved, "
    "and the scanned pages are kept so you can make it later."
)


class DocumentsSide:
    """Documents mode: the form, whether ``ocrmypdf`` is there, and how far the PDF has got.

    The PDFs made are the controller's, with the photos: it sets each mode's results aside while
    the other mode is on the page.
    """

    mode = Mode.DOCUMENTS

    def __init__(self, setup: DocumentSetup) -> None:
        self.form = setup.form
        self.tools = setup.tools
        self.save_form = setup.save_form
        self.ocr_available = False
        self.ocr_hint = ""
        self.pdf_page = 0
        self.pdf_total = 0
        self.ocr_running = False
        self.look_for_ocr()

    @property
    def searchable_checked(self) -> bool:
        """Whether the Searchable text box shows a tick: wanted, and possible."""
        return self.form.searchable and self.ocr_available

    def set_field(self, name: str, value: object) -> None:
        self.form = update_document_field(self.form, name, value)

    def look_for_ocr(self) -> None:
        """Ask the machine for ``ocrmypdf`` again: the answer is kept until the next look."""
        self.ocr_available = self.tools.ocr_available
        self.ocr_hint = "" if self.ocr_available else self.tools.ocr_hint

    def reset_progress(self) -> None:
        self.pdf_page, self.pdf_total, self.ocr_running = 0, 0, False

    def errors(self, shared: dict[str, str]) -> dict[str, str]:
        """The folder (shared with Photos) and the Documents fields; a photo album is no business
        of a document."""
        folder = {name: message for name, message in shared.items() if name == FOLDER_FIELD}
        return {**folder, **validate_document_form(self.form)}

    def destination(self, form: ScanForm) -> str | None:
        return document_destination(self.form, form.output_folder)

    def progress_text(self, state: State, pages: int, photos: int, *, checking: bool) -> str:
        return document_progress_text(
            state,
            pages,
            pdf_page=self.pdf_page,
            pdf_total=self.pdf_total,
            ocr=self.ocr_running,
            checking=checking,
        )

    def begin_scan(self, worker: WorkerPort, form: ScanForm) -> None:
        worker.scan_documents(
            self.form, form.output_folder, ocr_available=self.ocr_available, checked=True
        )

    def close_title(self, state: State) -> str:
        return CLOSE_PDF_TITLE if state is State.PROCESSING else CLOSE_SCAN_TITLE

    def close_text(self, state: State) -> str:
        return CLOSE_PDF_TEXT if state is State.PROCESSING else CLOSE_SCAN_TEXT

    def documents_after(
        self, shown: tuple[DocumentItem, ...], result: DocumentSessionResult
    ) -> tuple[DocumentItem, ...]:
        """The PDFs listed once ``result`` is in: one more when it made a PDF."""
        if result.document is None:
            return shown
        return (*shown, *items_from_document(result.document))

    def result_banner(self, final: State, result: DocumentSessionResult) -> Banner | None:
        return document_result_banner(final, result)

    def error_banner(self, error: BaseException, kept: DocumentSessionResult | None) -> Banner:
        if kept is None:
            return document_error_banner(error)
        return document_error_banner(error, kept.raw_dir, kept.raw_reason)

    def offers_kept(self, result: DocumentSessionResult) -> bool:
        return offers_kept(result)

    def kept_text(self, result: DocumentSessionResult) -> str:
        return document_kept_text(result)

    def kept_after_process(self, kept: DocumentSessionResult) -> DocumentSessionResult:
        """Kept as they are: the pages stay on offer until a PDF exists. Nothing was written, so
        another go repeats nothing."""
        return kept
