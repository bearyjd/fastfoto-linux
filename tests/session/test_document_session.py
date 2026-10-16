"""``run_document_session``: scan the feeder, make one PDF, report through callbacks."""

import threading
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from fastfoto_linux.documents import (
    AllPagesBlankError,
    ColourMode,
    DocumentError,
    UnsupportedPageError,
)
from fastfoto_linux.scanner import NoDocumentsError, ScannerStuckError
from fastfoto_linux.session import DocumentRawReason, RawPolicy, Stage
from tests.cli.fakes import DEVICE
from tests.documents.helpers import blank_scene, page_size_pt, reader, text_scene
from tests.session.conftest import STAMP, kept_names, raw_leftovers
from tests.session.doc_session_helpers import make_doc_request, run_doc

pytestmark = pytest.mark.usefixtures("no_real_ocr")


@dataclass
class Heard:
    """What the callbacks of one session were told, in order."""

    pages: list[int] = field(default_factory=list)
    stages: list[Stage] = field(default_factory=list)

    def callbacks(self) -> dict:
        return {"on_page": self.pages.append, "on_stage": self.stages.append}


def visible(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir() if not p.name.startswith("."))


def test_a_clean_run_makes_one_pdf_and_leaves_no_raw_pages(out, doc_transport) -> None:
    doc_transport.scenes = [text_scene(1), text_scene(2)]
    result = run_doc(make_doc_request(out), doc_transport)
    assert result.ok
    assert result.error is None
    assert not result.cancelled
    assert result.pages_scanned == 2
    document = result.document
    assert document is not None
    assert document.pdf == out / "Document_0001.pdf"
    assert (document.pages_read, document.pages_in_pdf, document.dropped) == (2, 2, ())
    assert len(reader(document.pdf.read_bytes()).pages) == 2
    assert (result.raw_dir, result.raw_reason, result.kept_pages) == (None, None, ())
    assert raw_leftovers(out) == []
    assert visible(out) == ["Document_0001.pdf"]


def test_blank_pages_are_dropped_and_numbered_as_scanned(out, doc_transport) -> None:
    doc_transport.scenes = [text_scene(1), blank_scene(2), text_scene(3), blank_scene(4)]
    result = run_doc(make_doc_request(out), doc_transport)
    assert result.document is not None
    assert result.document.dropped == (2, 4)
    assert result.document.pages_in_pdf == 2


def test_keep_blank_keeps_every_scanned_page(out, doc_transport) -> None:
    doc_transport.scenes = [text_scene(1), blank_scene(2)]
    result = run_doc(make_doc_request(out, keep_blank=True), doc_transport)
    assert result.document is not None
    assert (result.document.dropped, result.document.pages_in_pdf) == ((), 2)
    assert raw_leftovers(out) == []


def test_the_pdf_is_named_after_the_name_in_the_settings(out, doc_transport) -> None:
    doc_transport.scenes = [text_scene(1)]
    result = run_doc(make_doc_request(out, name="Tax Return"), doc_transport)
    assert result.document is not None
    assert result.document.pdf.name == "Tax Return_0001.pdf"


@pytest.mark.parametrize("colour", list(ColourMode))
def test_every_colour_mode_makes_a_pdf_from_the_colour_pages(out, doc_transport, colour) -> None:
    doc_transport.scenes = [text_scene(1)]
    result = run_doc(make_doc_request(out, colour=colour), doc_transport)
    assert result.ok
    assert len(reader(result.document.pdf.read_bytes()).pages) == 1


# --- callbacks -------------------------------------------------------------------------------


def test_the_stages_are_scanning_processing_done(out, doc_transport) -> None:
    doc_transport.scenes = [text_scene(1), text_scene(2)]
    heard = Heard()
    run_doc(make_doc_request(out), doc_transport, **heard.callbacks())
    assert heard.stages == [Stage.SCANNING, Stage.PROCESSING, Stage.DONE]
    assert heard.pages == [1, 2]


def test_a_checked_scanner_announces_checking_first_and_gets_the_cancel_event(
    out, doc_transport
) -> None:
    doc_transport.scenes = [text_scene(1)]
    calls: list[tuple[str, threading.Event | None]] = []

    def check(device: str, *, cancel: threading.Event | None) -> None:
        calls.append((device, cancel))

    heard = Heard()
    cancel = threading.Event()
    run_doc(
        make_doc_request(out), doc_transport, precheck=check, cancel=cancel, **heard.callbacks()
    )
    assert heard.stages == [Stage.CHECKING, Stage.SCANNING, Stage.PROCESSING, Stage.DONE]
    assert calls == [(DEVICE, cancel)]


def test_a_failing_done_callback_costs_the_result_nothing(out, doc_transport) -> None:
    doc_transport.scenes = [text_scene(1)]

    def on_stage(stage: Stage) -> None:
        if stage is Stage.DONE:
            raise RuntimeError("the window is gone")

    result = run_doc(make_doc_request(out), doc_transport, on_stage=on_stage)
    assert isinstance(result.error, RuntimeError)
    assert result.document is not None
    assert (out / "Document_0001.pdf").is_file()


# --- the resolution of a scanned page ---------------------------------------------------------


def test_a_page_that_does_not_say_its_resolution_is_taken_at_the_one_that_was_asked(
    out, doc_transport
) -> None:
    doc_transport.dpi_in_file = False
    doc_transport.scenes = [text_scene(1)]  # 850 pixels wide
    result = run_doc(make_doc_request(out, dpi=600), doc_transport)
    assert result.ok
    width, _ = page_size_pt(reader(result.document.pdf.read_bytes()), 0)
    assert width == pytest.approx(850 * 72 / 600, abs=0.5)


def test_a_page_that_says_its_resolution_keeps_it(out, doc_transport) -> None:
    doc_transport.scenes = [text_scene(1)]  # saved as 100 dpi
    result = run_doc(make_doc_request(out, dpi=600), doc_transport)
    width, _ = page_size_pt(reader(result.document.pdf.read_bytes()), 0)
    assert width == pytest.approx(850 * 72 / 100, abs=0.5)


# --- what goes wrong before the PDF ------------------------------------------------------------


def test_a_feeder_without_paper_is_an_error_and_leaves_nothing_behind(out, doc_transport) -> None:
    doc_transport.failure = lambda pages: NoDocumentsError("the document feeder is empty")
    result = run_doc(make_doc_request(out), doc_transport)
    assert isinstance(result.error, NoDocumentsError)
    assert not result.ok
    assert result.document is None
    assert (result.raw_dir, result.raw_reason, result.kept_pages) == (None, None, ())
    assert visible(out) == []
    assert raw_leftovers(out) == []


def test_a_scanner_that_does_not_answer_ends_the_session_before_the_scan(
    out, doc_transport
) -> None:
    def check(device: str, *, cancel: threading.Event | None) -> None:
        raise ScannerStuckError()

    result = run_doc(make_doc_request(out), doc_transport, precheck=check)
    assert isinstance(result.error, ScannerStuckError)
    assert doc_transport.jobs == []
    assert result.pages_scanned == 0
    assert raw_leftovers(out) == []


def test_pages_that_are_all_blank_make_no_pdf_and_keep_the_raw_pages_even_when_discarding(
    out, doc_transport
) -> None:
    doc_transport.scenes = [blank_scene(1), blank_scene(2)]
    result = run_doc(make_doc_request(out, policy=RawPolicy.DISCARD), doc_transport)
    assert isinstance(result.error, AllPagesBlankError)
    assert result.document is None
    assert visible(out) == []
    assert result.raw_dir == out / ".raw" / STAMP
    assert result.raw_reason is DocumentRawReason.ERROR
    assert kept_names(result.raw_dir) == ["page-0001.png", "page-0002.png"]


def test_an_unusable_page_stops_the_pdf_and_keeps_the_raw_pages(out, doc_transport) -> None:
    doc_transport.scenes = [text_scene(1), text_scene(2), text_scene(3)]
    doc_transport.corrupt_page = 2
    result = run_doc(make_doc_request(out, policy=RawPolicy.DISCARD), doc_transport)
    assert isinstance(result.error, UnsupportedPageError)
    assert isinstance(result.error, DocumentError)
    assert visible(out) == []  # a PDF with a page missing is worse than none
    assert result.raw_reason is DocumentRawReason.ERROR
    assert kept_names(result.raw_dir) == ["page-0001.png", "page-0002.png", "page-0003.png"]
    assert [page.name for page in result.kept_pages] == ["page-0001.png", "page-0003.png"]
