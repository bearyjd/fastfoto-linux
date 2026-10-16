"""What is logged when the scanner stops part-way: the photo wording is as it always was."""

import logging

import pytest

from fastfoto_linux.scanner import ScanError
from tests.documents.helpers import text_scene
from tests.process_helpers import plain_sheet
from tests.session.conftest import make_request, run
from tests.session.doc_session_helpers import make_doc_request, run_doc

PHOTO_LINE = "the scan stopped early; processing the 3 finished pages"
DOCUMENT_LINE = (
    "the scan stopped early, after 2 finished pages; no PDF is made from part of a stack"
)


def jam(pages):
    return ScanError("paper jam", returncode=1, pages=pages)


def stopped_early(caplog) -> list[str]:
    return [m for m in caplog.messages if "stopped early" in m]


def test_a_photo_scan_that_stops_early_logs_what_it_always_did(out, transport, caplog) -> None:
    transport.sheets = [plain_sheet(0), plain_sheet(1)]
    transport.keep_on_disk = transport.pages_before_failure = 3
    transport.failure = jam
    with caplog.at_level(logging.ERROR):
        run(make_request(out), transport)
    assert stopped_early(caplog) == [PHOTO_LINE]
    assert [r.name for r in caplog.records if "stopped early" in r.message] == [
        "fastfoto_linux.session.run"
    ]


@pytest.mark.usefixtures("no_real_ocr")
def test_a_document_scan_that_stops_early_says_no_pdf_is_made(out, doc_transport, caplog) -> None:
    doc_transport.scenes = [text_scene(1), text_scene(2), text_scene(3)]
    doc_transport.pages_before_failure = 2
    doc_transport.failure = jam
    with caplog.at_level(logging.ERROR):
        run_doc(make_doc_request(out), doc_transport)
    assert stopped_early(caplog) == [DOCUMENT_LINE]
