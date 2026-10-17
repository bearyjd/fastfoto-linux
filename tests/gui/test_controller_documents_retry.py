"""Documents mode keeps the way back: pages that no PDF has been made of stay on offer."""

import errno
from pathlib import Path

import pytest

from fastfoto_linux.documents import AllPagesBlankError, OcrMissingError
from fastfoto_linux.documents.errors import OutputFolderMissingError
from fastfoto_linux.gui.state import Mode, State
from fastfoto_linux.session import DocumentRawReason, DocumentSessionResult
from tests.gui.doc_helpers import clean_document, pages_in
from tests.gui.helpers import cancelled_scan
from tests.gui.test_controller_documents import Page

TEMP_FILE = "/out/.Document_0001.pdf.4944506a.tmp"


@pytest.fixture
def page(out: Path) -> Page:
    return Page(out)


def kept_after(raw: Path, error: Exception, pages: int = 3) -> DocumentSessionResult:
    return DocumentSessionResult(
        error=error,
        pages_scanned=pages,
        raw_dir=raw,
        raw_reason=DocumentRawReason.ERROR,
        kept_pages=pages_in(raw, pages),
    )


def test_a_pdf_that_could_not_be_saved_leaves_the_pages_on_offer(page: Page) -> None:
    controller = page.cancelled(3)
    controller.process_kept()
    raw = page.out / ".raw" / "s"
    disk_full = OSError(errno.ENOSPC, "No space left on device", TEMP_FILE)
    controller.on_finished(kept_after(raw, disk_full))
    assert controller.state is State.FAILED
    assert controller.banner is not None
    assert controller.banner.text == (
        f"No PDF was made. The disk is full. Raw pages kept in {raw} (something went wrong)."
    )
    assert controller.can_process_kept
    assert controller.process_kept_text == "Process them now"
    assert controller.kept_text == f"3 pages are kept in {raw}. Fix the problem, then make the PDF."


def test_the_first_run_offers_the_pages_after_a_problem_with_saving(page: Page) -> None:
    controller = page.scanning()
    raw = page.out / ".raw" / "s"
    not_allowed = PermissionError(errno.EACCES, "Permission denied", TEMP_FILE)
    controller.on_finished(kept_after(raw, not_allowed))
    assert controller.state is State.FAILED
    assert controller.banner is not None
    assert controller.banner.text == (
        "No PDF was made. The folder cannot be written to (permission denied). "
        f"Raw pages kept in {raw} (something went wrong)."
    )
    assert controller.can_process_kept
    controller.process_kept()  # a retry from a failed run
    assert controller.state is State.PROCESSING
    assert "process_kept" in page.worker.names


@pytest.mark.parametrize(
    ("error", "said"),
    [
        (
            OutputFolderMissingError("the output folder /out is not an existing folder"),
            "The output folder /out is not an existing folder.",
        ),
        (
            OcrMissingError("searchable text needs ocrmypdf, which is not installed"),
            "Searchable text needs ocrmypdf, which is not installed.",
        ),
    ],
)
def test_a_refusal_when_the_pages_are_made_is_not_a_scan_that_did_not_start(
    page: Page, error: Exception, said: str
) -> None:
    controller = page.cancelled(3)
    controller.process_kept()
    controller.on_finished(kept_after(page.out / ".raw" / "s", error))
    assert controller.banner is not None
    assert controller.banner.text.startswith(f"No PDF was made. {said}")
    assert controller.can_process_kept  # fix the folder, install the tool, or go on without it


def test_pages_that_a_retry_would_not_help_are_not_offered(page: Page) -> None:
    controller = page.cancelled(3)
    controller.process_kept()
    blank = AllPagesBlankError("all 3 pages look blank, so no PDF was written")
    controller.on_finished(kept_after(page.out / ".raw" / "s", blank))
    assert not controller.can_process_kept


def test_the_pages_stay_on_offer_until_a_pdf_exists(page: Page) -> None:
    controller = page.cancelled(3)
    controller.process_kept()
    controller.on_error(RuntimeError("something nobody foresaw"))
    assert controller.state is State.FAILED
    assert controller.can_process_kept  # the pages are still on disk: try again
    controller.process_kept()
    controller.on_finished(
        DocumentSessionResult(
            document=clean_document(page.out, pages=3).document,
            pages_scanned=3,
            raw_dir=page.out / ".raw" / "s",
            raw_reason=DocumentRawReason.CANCELLED,
        )
    )
    assert controller.state is State.DONE
    assert not controller.can_process_kept


def test_photos_offer_their_pages_once_as_before(out: Path) -> None:
    """The Photos rule is unchanged: a second go would write the photos already saved again."""
    page = Page(out, mode=Mode.PHOTOS)
    controller = page.scanning()
    controller.on_finished(cancelled_scan(out / ".raw" / "s", 4))
    assert controller.can_process_kept
    controller.process_kept()
    controller.on_error(RuntimeError("boom"))
    assert not controller.can_process_kept
