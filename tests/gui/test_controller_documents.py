"""Documents mode on the scan page's logic: the mode, its form, its stages and its results."""

from pathlib import Path

import pytest

from fastfoto_linux.documents import AllPagesBlankError, DocumentSettingsError, OcrStatus
from fastfoto_linux.gui.controller import Controller
from fastfoto_linux.gui.docform import DocumentForm
from fastfoto_linux.gui.doctools import (
    FLATPAK_OCR_HINT,
    NATIVE_OCR_HINT,
    DocumentSetup,
    DocumentTools,
)
from fastfoto_linux.gui.documents import item_from_document
from fastfoto_linux.gui.form import ScanForm
from fastfoto_linux.gui.state import ActionBlockedError, Mode, State
from fastfoto_linux.scanner import ScanError, ScannerNotFoundError
from fastfoto_linux.session import DocumentRawReason, DocumentSessionResult, Stage
from tests.gui.doc_helpers import (
    DocFakeWorker,
    cancelled_document,
    clean_document,
    pages_in,
    stopped_document,
)
from tests.gui.helpers import clean_result


class Page:
    """A controller with a fake worker; ``ocr`` is where OCRmyPDF is found (None: nowhere)."""

    def __init__(self, out: Path, *, mode: Mode = Mode.DOCUMENTS, ocr: str | None = "/x") -> None:
        self.out = out
        self.ocr = ocr
        self.flatpak = False
        self.worker = DocFakeWorker()
        self.photo_saves: list[ScanForm] = []
        self.document_saves: list[DocumentForm] = []
        self.mode_saves: list[Mode] = []
        tools = DocumentTools(find_ocr=lambda: self.ocr, in_flatpak=lambda: self.flatpak)
        setup = DocumentSetup(
            mode=mode,
            tools=tools,
            save_form=self.document_saves.append,
            save_mode=self.mode_saves.append,
        )
        self.controller = Controller(
            self.worker,
            ScanForm(output_folder=str(out)),
            save_form=self.photo_saves.append,
            documents=setup,
        )

    def ready(self) -> Controller:
        self.controller.check_scanner()
        self.controller.on_scanner(None)
        return self.controller

    def scanning(self) -> Controller:
        controller = self.ready()
        controller.start_scan()
        return controller

    def processing(self) -> Controller:
        controller = self.scanning()
        controller.on_stage(Stage.PROCESSING)
        return controller

    def cancelled(self, pages: int = 3) -> Controller:
        controller = self.scanning()
        controller.cancel()
        controller.on_finished(cancelled_document(self.out / ".raw" / "s", pages))
        return controller


@pytest.fixture
def page(out: Path) -> Page:
    return Page(out)


# -- the mode --------------------------------------------------------------------------------


def test_the_page_starts_in_photos_mode_unless_the_setup_says_otherwise(out: Path) -> None:
    plain = Controller(DocFakeWorker(), ScanForm(output_folder=str(out)))
    assert plain.mode is Mode.PHOTOS
    assert plain.document_form == DocumentForm()
    assert Page(out).controller.mode is Mode.DOCUMENTS


def test_the_mode_is_switched_and_remembered(out: Path) -> None:
    page = Page(out, mode=Mode.PHOTOS)
    page.controller.set_mode(Mode.DOCUMENTS)
    assert page.controller.mode is Mode.DOCUMENTS
    page.controller.set_mode("photos")
    assert page.controller.mode is Mode.PHOTOS
    assert page.mode_saves == [Mode.DOCUMENTS, Mode.PHOTOS]


def test_switching_to_the_mode_it_is_in_changes_nothing(page: Page) -> None:
    page.controller.set_mode(Mode.DOCUMENTS)
    assert page.mode_saves == []


def test_a_mode_that_does_not_exist_is_a_programming_error(page: Page) -> None:
    with pytest.raises(ValueError, match="mode"):
        page.controller.set_mode("scans")


@pytest.mark.parametrize("busy", ["scanning", "processing", "cancelling"])
def test_the_mode_cannot_change_while_a_job_runs(page: Page, busy: str) -> None:
    controller = {
        "scanning": page.scanning,
        "processing": page.processing,
        "cancelling": lambda: (page.scanning(), page.controller.cancel(), page.controller)[2],
    }[busy]()
    with pytest.raises(ActionBlockedError):
        controller.set_mode(Mode.PHOTOS)
    assert controller.mode is Mode.DOCUMENTS


def test_a_changed_mode_is_announced(out: Path) -> None:
    changes: list[int] = []
    controller = Controller(
        DocFakeWorker(), ScanForm(output_folder=str(out)), on_change=lambda: changes.append(1)
    )
    controller.set_mode(Mode.DOCUMENTS)
    assert changes


def test_each_mode_keeps_its_own_values_and_the_folder_is_shared(
    page: Page, tmp_path: Path
) -> None:
    controller = page.ready()
    controller.set_document_field("name", "Lease")
    controller.set_document_field("dpi", 600)
    controller.set_mode(Mode.PHOTOS)
    controller.set_field("album", "Rome")
    other = tmp_path / "other"
    other.mkdir()
    controller.set_field("output_folder", str(other))
    controller.set_mode(Mode.DOCUMENTS)
    assert (controller.document_form.name, controller.document_form.dpi) == ("Lease", 600)
    assert controller.form.album == "Rome"
    assert controller.form.output_folder == str(other)
    assert controller.destination == f"{other}/Lease_####.pdf"


def test_a_state_left_by_the_other_mode_is_a_ready_page(page: Page) -> None:
    controller = page.processing()
    controller.on_finished(clean_document(page.out))
    assert controller.state is State.DONE
    controller.set_mode(Mode.PHOTOS)
    assert controller.state is State.READY
    assert controller.can_scan


def test_a_mode_switch_before_the_scanner_is_checked_keeps_the_page_idle(page: Page) -> None:
    page.controller.set_mode(Mode.PHOTOS)
    assert page.controller.state is State.IDLE


# -- the form --------------------------------------------------------------------------------


def test_a_document_field_is_set_and_only_the_document_form_changes(page: Page) -> None:
    before = page.controller.form
    page.controller.set_document_field("colour", "grey")
    page.controller.set_document_field("both_sides", False)
    assert page.controller.document_form.colour == "grey"
    assert page.controller.document_form.both_sides is False
    assert page.controller.form == before


def test_a_field_the_form_does_not_have_is_refused(page: Page) -> None:
    with pytest.raises(ValueError, match="no field"):
        page.controller.set_document_field("album", "x")


def test_in_documents_mode_only_the_documents_fields_are_checked(page: Page) -> None:
    controller = page.controller
    controller.set_field("album", "///")  # a photo album that cannot be used
    controller.set_document_field("langs", "!")
    assert list(controller.errors) == ["langs"]


def test_in_photos_mode_the_documents_fields_are_not_checked(page: Page) -> None:
    controller = page.controller
    controller.set_document_field("langs", "!")
    controller.set_mode(Mode.PHOTOS)
    assert controller.errors == {}
    controller.set_field("album", "///")
    assert list(controller.errors) == ["album"]


def test_the_folder_is_checked_in_both_modes(page: Page, tmp_path: Path) -> None:
    controller = page.controller
    controller.set_field("output_folder", str(tmp_path / "gone"))
    controller.check_disk()
    assert "does not exist" in controller.errors["output_folder"]
    controller.set_mode(Mode.PHOTOS)
    assert "output_folder" in controller.errors


def test_scan_is_blocked_by_a_bad_document_field_and_says_why(page: Page) -> None:
    controller = page.ready()
    assert controller.can_scan
    controller.set_document_field("name", "///")
    assert not controller.can_scan
    assert "file name" in controller.scan_blocker
    with pytest.raises(ActionBlockedError):
        controller.start_scan()


def test_the_destination_is_the_pdf_that_will_be_made(page: Page) -> None:
    assert page.controller.destination == f"{page.out}/Document_####.pdf"
    page.controller.set_document_field("name", "///")
    assert page.controller.destination is None


# -- searchable text -------------------------------------------------------------------------


def test_searchable_text_is_available_when_ocrmypdf_is_found(page: Page) -> None:
    assert page.controller.ocr_available is True
    assert page.controller.ocr_hint == ""
    assert page.controller.searchable_checked is True


def test_searchable_text_is_off_and_explained_when_ocrmypdf_is_missing(out: Path) -> None:
    page = Page(out, ocr=None)
    assert page.controller.ocr_available is False
    assert page.controller.ocr_hint == NATIVE_OCR_HINT
    assert (
        page.controller.searchable_checked is False
    )  # the box cannot show a tick it cannot honour
    assert page.controller.document_form.searchable is True  # what was asked for is remembered


def test_inside_a_flatpak_the_hint_says_the_native_install_is_needed(out: Path) -> None:
    page = Page(out, ocr=None)
    page.flatpak = True
    page.controller.set_mode(Mode.PHOTOS)
    page.controller.set_mode(Mode.DOCUMENTS)
    assert page.controller.ocr_hint == FLATPAK_OCR_HINT


def test_ocrmypdf_installed_while_the_app_runs_is_noticed_at_the_next_look(out: Path) -> None:
    page = Page(out, ocr=None)
    page.ocr = "/usr/bin/ocrmypdf"
    page.controller.check_scanner()
    assert page.controller.ocr_available is True


def test_unchecking_searchable_text_is_a_choice_that_stays(page: Page) -> None:
    page.controller.set_document_field("searchable", False)
    assert page.controller.searchable_checked is False


# -- running a scan --------------------------------------------------------------------------


def test_a_scan_goes_to_the_worker_with_the_documents_form_and_the_shared_folder(
    page: Page,
) -> None:
    controller = page.ready()
    controller.set_document_field("name", "Lease")
    controller.start_scan()
    ((name, (form, folder, ocr, checked)),) = [c for c in page.worker.calls if c[0] != "check"]
    assert name == "scan_documents"
    assert (form.name, folder, ocr, checked) == ("Lease", str(page.out), True, True)
    assert controller.state is State.SCANNING


def test_a_scan_remembers_the_documents_form_and_the_shared_folder(page: Page) -> None:
    page.ready().set_document_field("name", "Lease")
    page.controller.start_scan()
    assert [form.name for form in page.document_saves] == ["Lease"]
    assert [form.output_folder for form in page.photo_saves] == [str(page.out)]


def test_the_stages_read_in_the_words_of_the_brief(page: Page) -> None:
    controller = page.scanning()
    assert controller.progress_text == "Scanning page 1"
    controller.on_stage(Stage.CHECKING)
    assert controller.progress_text == "Checking the scanner…"
    controller.on_stage(Stage.SCANNING)
    controller.on_page(1)
    controller.on_page(2)
    assert controller.progress_text == "Scanning page 3"
    controller.on_stage(Stage.PROCESSING)
    assert controller.state is State.PROCESSING
    assert controller.progress_text == "Making the PDF…"
    controller.on_build_page((2, 5))
    assert controller.progress_text == "Making the PDF (page 2 of 5)"
    controller.on_ocr()
    assert controller.progress_text == "Adding searchable text…"
    controller.on_finished(clean_document(page.out))
    assert controller.progress_text == ""


def test_progress_of_an_old_run_does_not_leak_into_the_next(page: Page) -> None:
    controller = page.processing()
    controller.on_build_page((3, 3))
    controller.on_ocr()
    controller.on_finished(clean_document(page.out))
    controller.start_scan()
    controller.on_stage(Stage.PROCESSING)
    assert controller.progress_text == "Making the PDF…"


def test_progress_that_arrives_late_is_ignored(page: Page) -> None:
    controller = page.ready()
    controller.on_build_page((1, 3))
    controller.on_ocr()
    assert controller.progress_text == ""
    assert controller.state is State.READY


def test_a_clean_run_lists_the_pdf_and_says_where_it_is(page: Page) -> None:
    controller = page.processing()
    result = clean_document(page.out, pages=3, dropped=(2,))
    controller.on_finished(result)
    assert controller.state is State.DONE
    assert controller.documents == (item_from_document(result.document),)
    assert controller.photos == ()
    assert controller.results_folder == page.out
    assert controller.banner is not None
    assert controller.banner.kind == "positive"
    assert controller.banner.text.startswith(f"Document_0001.pdf saved to {page.out}: 3 pages.")


def test_a_new_scan_clears_the_list_of_the_last(page: Page) -> None:
    controller = page.processing()
    controller.on_finished(clean_document(page.out))
    assert controller.documents
    controller.start_scan()
    assert controller.documents == ()
    assert controller.banner is None


def test_a_failed_ocr_is_a_warning_and_the_item_carries_it(page: Page) -> None:
    controller = page.processing()
    controller.on_finished(clean_document(page.out, ocr=OcrStatus.FAILED, detail="exit 6"))
    assert controller.banner is not None
    assert controller.banner.kind == "warning"
    assert controller.documents[0].ocr_warning


def test_the_scanner_lost_during_a_scan_is_noticed_in_documents_mode_too(page: Page) -> None:
    controller = page.scanning()
    controller.on_finished(DocumentSessionResult(error=ScannerNotFoundError("the scanner is gone")))
    assert controller.state is State.FAILED
    assert not controller.scanner_ready


# -- cancelling ------------------------------------------------------------------------------


def test_cancel_works_while_scanning_and_while_making_the_pdf(page: Page) -> None:
    controller = page.scanning()
    assert controller.can_cancel
    controller.cancel()
    assert controller.state is State.CANCELLING
    controller.on_finished(cancelled_document(page.out / ".raw" / "s"))
    assert controller.state is State.CANCELLED

    controller.start_scan()
    controller.on_stage(Stage.PROCESSING)
    assert controller.can_cancel
    controller.cancel()
    assert controller.state is State.CANCELLING
    assert ("cancel", None) in page.worker.calls


def test_a_cancel_that_kept_pages_offers_to_make_the_pdf(page: Page) -> None:
    controller = page.cancelled(3)
    assert controller.can_process_kept
    raw = page.out / ".raw" / "s"
    assert controller.kept_text == f"3 pages were scanned before you cancelled — kept in {raw}"
    assert controller.process_kept_text == "Process them now"
    assert controller.process_kept_folder == str(page.out)
    assert controller.banner is not None
    assert controller.banner.kind == "info"


def test_process_them_now_hands_the_kept_result_to_the_worker(page: Page) -> None:
    controller = page.cancelled(3)
    kept = controller._result
    controller.process_kept()
    assert ("process_kept", kept) in page.worker.calls
    assert controller.state is State.PROCESSING
    assert controller.banner is None
    assert not controller.can_process_kept


def test_the_pdf_made_from_kept_pages_is_listed(page: Page) -> None:
    controller = page.cancelled(3)
    controller.process_kept()
    result = clean_document(page.out, pages=3)
    controller.on_finished(
        DocumentSessionResult(
            document=result.document,
            pages_scanned=3,
            raw_dir=page.out / ".raw" / "s",
            raw_reason=DocumentRawReason.CANCELLED,
        )
    )
    assert controller.state is State.DONE
    assert len(controller.documents) == 1
    assert not controller.can_process_kept


def test_kept_pages_cancelled_again_can_be_offered_again(page: Page) -> None:
    controller = page.cancelled(3)
    controller.process_kept()
    controller.cancel()
    controller.on_finished(cancelled_document(page.out / ".raw" / "s", 3))
    assert controller.state is State.CANCELLED
    assert controller.can_process_kept


def test_a_scanner_that_stopped_part_way_offers_the_finished_pages(page: Page) -> None:
    controller = page.scanning()
    raw = page.out / ".raw" / "s"
    controller.on_finished(stopped_document(raw, ScanError("the paper jammed"), pages=2))
    assert controller.state is State.FAILED
    assert controller.can_process_kept
    assert "No PDF is made from part of a stack" in controller.kept_text
    assert controller.banner is not None
    assert controller.banner.kind == "error"
    assert controller.banner.text.startswith("The scan failed. the paper jammed.")


def test_pages_that_cannot_make_a_pdf_are_not_offered_again(page: Page) -> None:
    controller = page.scanning()
    raw = page.out / ".raw" / "s"
    controller.on_finished(
        DocumentSessionResult(
            error=AllPagesBlankError("all 2 pages look blank, so no PDF was written"),
            raw_dir=raw,
            raw_reason=DocumentRawReason.ERROR,
            kept_pages=pages_in(raw, 2),
        )
    )
    assert controller.state is State.FAILED
    assert not controller.can_process_kept
    assert controller.banner is not None
    assert controller.banner.text.startswith("No PDF was made. all 2 pages look blank")


def test_a_refusal_before_the_scan_is_said_as_such_and_the_scanner_stays_found(
    page: Page,
) -> None:
    controller = page.scanning()
    controller.on_error(DocumentSettingsError("the output folder /x is not an existing folder"))
    assert controller.state is State.FAILED
    assert controller.scanner_ready
    assert controller.banner is not None
    assert controller.banner.text == (
        "The scan did not start: the output folder /x is not an existing folder."
    )
    assert controller.can_scan is True  # nothing was scanned: the user can fix it and go again


# -- each mode shows its own results ---------------------------------------------------------


def test_the_other_modes_results_wait_for_the_user_to_come_back(page: Page) -> None:
    controller = page.processing()
    controller.on_finished(clean_document(page.out))
    controller.set_mode(Mode.PHOTOS)
    assert controller.documents == ()
    assert controller.banner is None
    assert controller.photos == ()
    controller.set_mode(Mode.DOCUMENTS)
    assert len(controller.documents) == 1
    assert controller.banner is not None
    assert controller.banner.kind == "positive"


def test_photos_results_are_not_shown_in_documents_mode(out: Path) -> None:
    page = Page(out, mode=Mode.PHOTOS)
    controller = page.scanning()
    controller.on_stage(Stage.PROCESSING)
    controller.on_finished(clean_result(out / "Album", photos=2))
    assert controller.banner is not None
    controller.set_mode(Mode.DOCUMENTS)
    assert controller.banner is None
    assert controller.documents == ()
    controller.set_mode(Mode.PHOTOS)
    assert controller.banner is not None
    assert controller.state is State.READY  # the page is ready; the results are the mode's


def test_pages_kept_in_one_mode_are_still_offered_when_the_user_comes_back(page: Page) -> None:
    controller = page.cancelled(3)
    controller.set_mode(Mode.PHOTOS)
    assert not controller.can_process_kept
    controller.set_mode(Mode.DOCUMENTS)
    assert controller.can_process_kept
    controller.process_kept()  # from READY: the state was settled when the mode changed
    assert controller.state is State.PROCESSING


# -- closing the window ----------------------------------------------------------------------


def test_closing_while_the_pdf_is_made_asks_about_the_pdf_not_about_photos(page: Page) -> None:
    controller = page.scanning()
    assert controller.close_title == "Cancel the scan?"
    controller.on_stage(Stage.PROCESSING)
    assert controller.close_title == "Cancel making the PDF?"
    assert "no PDF is saved" in controller.close_text
    assert "photos" not in controller.close_text


def test_closing_while_a_document_scan_runs_cancels_it_first(page: Page) -> None:
    controller = page.scanning()
    assert controller.request_close() is False
    assert controller.state is State.CANCELLING
    controller.on_finished(cancelled_document(page.out / ".raw" / "s"))
    assert controller.close_ready


def test_a_failure_of_the_page_itself_in_documents_mode_leaves_a_usable_page(page: Page) -> None:
    controller = page.ready()
    controller.fail(RuntimeError("boom"))
    assert controller.state is State.FAILED
    assert controller.banner is not None
    assert controller.banner.kind == "error"
