"""A document session that is stopped: cancelled, interrupted, aborted, or ended by the scanner."""

import logging
import threading
from typing import Any

import pytest

from fastfoto_linux.documents import OcrMode, build
from fastfoto_linux.scanner import ScanCancelledError, ScanError
from fastfoto_linux.session import DocumentRawReason, RawPolicy, Stage
from tests import _fake_ocrmypdf as fake
from tests.documents.helpers import text_scene
from tests.session.conftest import STAMP, kept_names, raw_leftovers
from tests.session.doc_session_helpers import make_doc_request, run_doc

pytestmark = pytest.mark.usefixtures("no_real_ocr")

PAGES = ["page-0001.png", "page-0002.png", "page-0003.png"]


def three_pages(transport):
    transport.scenes = [text_scene(1), text_scene(2), text_scene(3)]
    return transport


def no_pdf(out) -> bool:
    return not [p for p in out.iterdir() if p.suffix == ".pdf"]


def must_not_build(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("the pages must not be made into a PDF")


# --- a cancel during the scan ------------------------------------------------------------------


def test_a_cancel_during_the_scan_makes_no_pdf_and_keeps_the_pages_scanned_so_far(
    out, doc_transport
) -> None:
    three_pages(doc_transport)
    doc_transport.pages_before_failure = 2
    doc_transport.failure = lambda pages: ScanCancelledError("scan cancelled", pages=pages)
    result = run_doc(
        make_doc_request(out, policy=RawPolicy.DISCARD), doc_transport, build=must_not_build
    )
    assert result.cancelled
    assert result.error is None
    assert not result.ok
    assert result.document is None
    assert result.pages_scanned == 2
    assert result.raw_reason is DocumentRawReason.CANCELLED
    assert result.raw_dir == out / ".raw" / STAMP
    assert [page.name for page in result.kept_pages] == PAGES[:2]  # a third was cut off mid-write
    assert no_pdf(out)


def test_ctrl_c_during_the_scan_is_the_same_cancel_and_keeps_every_complete_page(
    out, doc_transport
) -> None:
    three_pages(doc_transport)
    doc_transport.failure = lambda pages: KeyboardInterrupt()
    result = run_doc(make_doc_request(out), doc_transport, build=must_not_build)
    assert result.cancelled
    assert result.raw_reason is DocumentRawReason.CANCELLED
    assert [page.name for page in result.kept_pages] == PAGES
    assert no_pdf(out)


def test_a_cancel_during_the_scan_does_not_announce_processing(out, doc_transport) -> None:
    three_pages(doc_transport)
    doc_transport.failure = lambda pages: ScanCancelledError("scan cancelled", pages=pages)
    stages: list[Stage] = []
    run_doc(make_doc_request(out), doc_transport, on_stage=stages.append)
    assert stages == [Stage.SCANNING, Stage.DONE]


# --- a cancel while the PDF is made --------------------------------------------------------------


def test_a_cancel_before_the_first_page_is_made_stops_the_pdf_and_keeps_the_pages(
    out, doc_transport
) -> None:
    three_pages(doc_transport)
    cancel = threading.Event()

    def on_stage(stage: Stage) -> None:
        if stage is Stage.PROCESSING:
            cancel.set()

    result = run_doc(
        make_doc_request(out, policy=RawPolicy.DISCARD),
        doc_transport,
        cancel=cancel,
        on_stage=on_stage,
    )
    assert result.cancelled
    assert result.error is None
    assert result.document is None
    assert result.pages_scanned == 3
    assert result.raw_reason is DocumentRawReason.CANCELLED
    assert kept_names(result.raw_dir) == PAGES
    assert [page.name for page in result.kept_pages] == PAGES
    assert no_pdf(out)


def test_a_cancel_after_some_pages_were_made_publishes_nothing(
    out, doc_transport, monkeypatch
) -> None:
    three_pages(doc_transport)
    cancel = threading.Event()
    real_trim = build.trim_page
    seen: list[int] = []

    def trim_then_cancel(page):
        seen.append(1)
        if len(seen) == 2:
            cancel.set()
        return real_trim(page)

    monkeypatch.setattr(build, "trim_page", trim_then_cancel)
    result = run_doc(make_doc_request(out), doc_transport, cancel=cancel)
    assert result.cancelled
    assert result.document is None
    assert len(seen) == 2  # the third page was never started
    assert no_pdf(out)
    assert kept_names(result.raw_dir) == PAGES


def test_an_interrupt_while_the_pdf_is_made_is_a_cancel(out, doc_transport) -> None:
    three_pages(doc_transport)

    def interrupt(*args: Any, **kwargs: Any) -> Any:
        raise KeyboardInterrupt

    stages: list[Stage] = []
    result = run_doc(
        make_doc_request(out, policy=RawPolicy.DISCARD),
        doc_transport,
        build=interrupt,
        on_stage=stages.append,
    )
    assert result.cancelled
    assert result.error is None
    assert result.document is None
    assert result.raw_reason is DocumentRawReason.CANCELLED
    assert kept_names(result.raw_dir) == PAGES
    assert stages == [Stage.SCANNING, Stage.PROCESSING, Stage.DONE]


# --- a cancel during the searchable text -------------------------------------------------------


def test_a_cancel_during_ocr_stops_ocrmypdf_publishes_nothing_and_keeps_the_pages(
    out, doc_transport, monkeypatch
) -> None:
    record = out.parent / "record.json"
    fake.put_on_path(out.parent / "bin", monkeypatch)
    fake.configure(monkeypatch, mode="hang", record_to=str(record), child=True)
    three_pages(doc_transport)
    cancel = threading.Event()
    fake.when_started(record, cancel.set)
    result = run_doc(
        make_doc_request(out, policy=RawPolicy.DISCARD, ocr=OcrMode.ON),
        doc_transport,
        cancel=cancel,
    )
    assert result.cancelled
    assert result.document is None
    assert result.raw_reason is DocumentRawReason.CANCELLED
    assert kept_names(result.raw_dir) == PAGES
    assert no_pdf(out)
    seen = fake.read_record(record)
    assert fake.wait_until_gone(seen["pid"])
    assert fake.wait_until_gone(seen["child"])


# --- the scanner stops part-way --------------------------------------------------------------


def test_a_scanner_error_part_way_makes_no_pdf_from_a_part_of_the_stack(out, doc_transport) -> None:
    three_pages(doc_transport)
    doc_transport.pages_before_failure = 2
    doc_transport.failure = lambda pages: ScanError("paper jam", returncode=1, pages=pages)
    stages: list[Stage] = []
    result = run_doc(
        make_doc_request(out, policy=RawPolicy.DISCARD),
        doc_transport,
        build=must_not_build,
        on_stage=stages.append,
    )
    assert isinstance(result.error, ScanError)
    assert not result.cancelled
    assert not result.ok
    assert result.document is None
    assert result.pages_scanned == 2
    assert result.raw_reason is DocumentRawReason.SCAN_ERROR
    assert [page.name for page in result.kept_pages] == PAGES[:2]
    assert no_pdf(out)
    assert Stage.PROCESSING not in stages


# --- an abort that is no Exception --------------------------------------------------------------


def test_an_abort_while_the_pdf_is_made_moves_the_pages_to_dot_raw_and_propagates(
    out, doc_transport
) -> None:
    three_pages(doc_transport)

    def abort(*args: Any, **kwargs: Any) -> Any:
        raise SystemExit(3)

    with pytest.raises(SystemExit) as raised:
        run_doc(make_doc_request(out, policy=RawPolicy.DISCARD), doc_transport, build=abort)
    assert raised.value.code == 3
    assert kept_names(out / ".raw" / STAMP) == PAGES
    assert [p for p in raw_leftovers(out) if p != ".raw"] == []


def test_a_failure_to_settle_never_replaces_the_abort(
    out, doc_transport, monkeypatch, caplog
) -> None:
    def refuse(*args: Any, **kwargs: Any) -> None:
        raise OSError("the disk is gone")

    monkeypatch.setattr("fastfoto_linux.session.documents.settle_raw_dir", refuse)
    three_pages(doc_transport)

    def abort(*args: Any, **kwargs: Any) -> Any:
        raise SystemExit(3)

    with (
        caplog.at_level(logging.ERROR, logger="fastfoto_linux.session"),
        pytest.raises(SystemExit) as raised,
    ):
        run_doc(make_doc_request(out, policy=RawPolicy.DISCARD), doc_transport, build=abort)
    assert raised.value.code == 3
    assert "the disk is gone" in caplog.text
