"""The worker with the real document session and the real PDF builder (a fake scanner only)."""

import functools
from pathlib import Path
from typing import Any

import pypdf
import pytest

from fastfoto_linux.documents import DocumentSettingsError, build_document
from fastfoto_linux.gui.docform import DocumentForm
from fastfoto_linux.gui.doctools import DocumentTools
from fastfoto_linux.gui.worker import Worker
from fastfoto_linux.scanner import ScanError, ScanTarget
from fastfoto_linux.session import DocumentRawReason, Stage, run_document_session
from tests import _fake_ocrmypdf as fake_ocr
from tests.cli.fakes import DEVICE
from tests.documents.helpers import blank_scene, text_scene
from tests.documents.scan_fakes import DocTransport
from tests.gui.doc_helpers import DocRecordingSink

WAIT = 10.0


@pytest.fixture(autouse=True)
def no_real_ocr(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """A machine that has ocrmypdf must not run it here."""
    fake_ocr.no_ocr_on_path(tmp_path_factory.mktemp("no-ocr"), monkeypatch)


def worker_for(sink: DocRecordingSink, transport: DocTransport) -> Worker:
    session = functools.partial(
        run_document_session, scan=transport.run_scan, precheck=lambda *args, **kwargs: None
    )
    tools = DocumentTools(session=session, build=build_document)
    return Worker(sink, discover=lambda: ScanTarget(device=DEVICE), documents=tools)


def run(worker: Worker, sink: DocRecordingSink, out: Path, **form: Any) -> None:
    sink.finished.clear()
    worker.scan_documents(DocumentForm(searchable=False, **form), str(out), ocr_available=False)
    assert sink.finished.wait(WAIT)
    worker.join(WAIT)


def test_a_stack_becomes_a_pdf_with_the_blank_back_left_out(out: Path) -> None:
    transport = DocTransport(scenes=[text_scene(1), blank_scene(2), text_scene(3)])
    sink = DocRecordingSink()
    run(worker_for(sink, transport), sink, out, name="Lease")
    result = sink.value("finished")
    assert result.ok
    assert result.document.dropped == (2,)
    assert result.document.pages_in_pdf == 2
    assert result.document.pdf == out / "Lease_0001.pdf"
    assert len(pypdf.PdfReader(result.document.pdf).pages) == 2
    assert result.raw_reason is DocumentRawReason.PAGES_DROPPED  # a dropped page keeps the pages
    assert [v for n, v in sink.events if n == "build_page"] == [(1, 3), (2, 3), (3, 3)]
    stages = [v for n, v in sink.events if n == "stage"]
    assert stages == [Stage.CHECKING, Stage.SCANNING, Stage.PROCESSING, Stage.DONE]


def test_the_session_is_the_authority_on_a_folder_that_is_gone(out: Path) -> None:
    sink = DocRecordingSink()
    transport = DocTransport(scenes=[text_scene(1)])
    worker = worker_for(sink, transport)
    worker.scan_documents(
        DocumentForm(searchable=False), str(out / "gone"), ocr_available=False, checked=True
    )
    assert sink.finished.wait(WAIT)
    worker.join(WAIT)
    error = sink.value("error")
    assert isinstance(error, DocumentSettingsError)
    assert "gone" in str(error)
    assert transport.jobs == []  # nothing was scanned for a PDF that could not be saved


def test_a_scanner_that_stops_part_way_leaves_pages_that_make_a_pdf_later(out: Path) -> None:
    transport = DocTransport(
        scenes=[text_scene(1), text_scene(2), text_scene(3)],
        pages_before_failure=2,
        failure=lambda pages: ScanError("the paper jammed", pages=pages),
    )
    sink = DocRecordingSink()
    worker = worker_for(sink, transport)
    run(worker, sink, out, name="Lease", dpi=200)
    stopped = sink.value("finished")
    assert isinstance(stopped.error, ScanError)
    assert stopped.document is None
    assert len(stopped.kept_pages) == 2
    assert [p.name for p in out.iterdir() if p.suffix == ".pdf"] == []  # no PDF of part of a stack

    sink.events.clear()
    sink.finished.clear()
    worker.process_kept(stopped)
    assert sink.finished.wait(WAIT)
    worker.join(WAIT)
    made = sink.events[-1][1]
    assert made.document.pdf == out / "Lease_0001.pdf"
    assert made.document.pages_in_pdf == 2
    assert [v for n, v in sink.events if n == "build_page"] == [(1, 2), (2, 2)]
    assert len(pypdf.PdfReader(made.document.pdf).pages) == 2


def test_kept_pages_that_are_all_blank_come_back_as_a_result_with_the_pages_still_kept(
    out: Path,
) -> None:
    transport = DocTransport(
        scenes=[blank_scene(1), blank_scene(2)],
        pages_before_failure=2,
        failure=lambda pages: ScanError("the cover was opened", pages=pages),
    )
    sink = DocRecordingSink()
    worker = worker_for(sink, transport)
    run(worker, sink, out)
    stopped = sink.value("finished")
    sink.events.clear()
    sink.finished.clear()
    worker.process_kept(stopped)
    assert sink.finished.wait(WAIT)
    worker.join(WAIT)
    again = sink.events[-1][1]
    assert again.document is None
    assert "blank" in str(again.error)
    assert again.kept_pages == stopped.kept_pages
    assert all(page.exists() for page in again.kept_pages)
