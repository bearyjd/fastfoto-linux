"""The way back after a failure, end to end: the page's controller, the real worker, the real
document session and PDF builder, a fake scanner and (where wanted) a fake ``ocrmypdf``."""

import errno
import functools
import os
import queue
import stat
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pypdf
import pytest

from fastfoto_linux.documents import OcrStatus, build_document, find_ocrmypdf
from fastfoto_linux.documents import build as build_module
from fastfoto_linux.gui.controller import Controller
from fastfoto_linux.gui.doctools import DocumentSetup, DocumentTools
from fastfoto_linux.gui.form import ScanForm
from fastfoto_linux.gui.state import Mode, State
from fastfoto_linux.gui.worker import Worker
from fastfoto_linux.scanner import ScanCancelledError, ScanTarget
from fastfoto_linux.session import run_document_session
from tests import _fake_ocrmypdf as fake_ocr
from tests.cli.fakes import DEVICE
from tests.documents.helpers import text_scene
from tests.documents.scan_fakes import DocTransport

WAIT = 30.0
ENDS = ("on_finished", "on_error", "on_scanner")


class QueueSink:
    """A worker sink that queues every report; the test hands them to the controller itself,
    on its own thread, as the window does."""

    def __init__(self) -> None:
        self.reports: queue.Queue[tuple[str, Any]] = queue.Queue()

    def __getattr__(self, name: str) -> Any:
        if not name.startswith("on_"):
            raise AttributeError(name)
        return lambda *args: self.reports.put((name, args[0] if args else True))


class Page:
    """The scan page of Documents mode on a real worker."""

    def __init__(self, out: Path, transport: DocTransport) -> None:
        session = functools.partial(
            run_document_session, scan=transport.run_scan, precheck=lambda *a, **k: None
        )
        tools = DocumentTools(
            session=session, build=build_document, find_ocr=find_ocrmypdf, in_flatpak=lambda: False
        )
        self.out = out
        self.sink = QueueSink()
        self.worker = Worker(self.sink, discover=lambda: ScanTarget(device=DEVICE), documents=tools)
        self.controller = Controller(
            self.worker,
            ScanForm(output_folder=str(out)),
            documents=DocumentSetup(mode=Mode.DOCUMENTS, tools=tools),
        )

    def pump(self) -> None:
        """Hand the worker's reports to the controller until the job ends."""
        while True:
            name, value = self.sink.reports.get(timeout=WAIT)
            getattr(self.controller, name)(value)
            if name in ENDS:
                self.worker.join(WAIT)
                return

    def scan(self) -> Controller:
        self.controller.check_scanner()
        self.pump()
        assert self.controller.scanner_ready
        self.controller.start_scan()
        self.pump()
        return self.controller

    def process(self) -> Controller:
        self.controller.process_kept()
        self.pump()
        return self.controller

    def pdfs(self) -> list[Path]:
        return sorted(self.out.glob("*.pdf"))


def three_pages(**options: Any) -> DocTransport:
    return DocTransport(scenes=[text_scene(1), text_scene(2), text_scene(3)], **options)


def cancelled_after_two() -> DocTransport:
    """A scanner that is stopped by the user after the second page."""
    return three_pages(
        pages_before_failure=2, failure=lambda pages: ScanCancelledError("cancelled", pages=pages)
    )


@pytest.fixture(autouse=True)
def no_real_ocr(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """A machine that has ocrmypdf must not run it here."""
    fake_ocr.no_ocr_on_path(tmp_path_factory.mktemp("no-ocr"), monkeypatch)


def disk_full_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """The first PDF to be saved meets a full disk, the next one does not."""
    real = build_module.publish_pdf
    calls: list[int] = []

    def publish(data: bytes, root: Path, name: str) -> Path:
        if not calls:
            calls.append(1)
            raise OSError(errno.ENOSPC, "No space left on device", str(root / f".{name}.4a.tmp"))
        return real(data, root, name)

    monkeypatch.setattr(build_module, "publish_pdf", publish)


def test_ocrmypdf_that_vanished_since_the_scan_still_gives_a_plain_pdf(
    out: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_ocr.put_on_path(tmp_path / "bin", monkeypatch)  # there when the scan starts ...
    page = Page(out, cancelled_after_two())
    controller = page.scan()
    assert controller.state is State.CANCELLED
    assert controller.can_process_kept
    assert controller.document_form.searchable  # the scan asked for searchable text
    fake_ocr.no_ocr_on_path(tmp_path / "gone", monkeypatch)  # ... and gone when the pages are made

    page.process()

    assert controller.state is State.DONE
    (item,) = controller.documents
    assert item.ocr is OcrStatus.UNAVAILABLE
    assert item.searchable_text == "Searchable text: no (OCRmyPDF and Tesseract are not installed)"
    assert controller.banner is not None
    assert controller.banner.kind == "warning"
    assert "searchable text was not added" in controller.banner.text
    assert not controller.can_process_kept
    (pdf,) = page.pdfs()
    assert len(pypdf.PdfReader(pdf).pages) == 2


def test_a_full_disk_when_the_pages_are_made_keeps_the_way_back(
    out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = Page(out, cancelled_after_two())
    controller = page.scan()
    disk_full_once(monkeypatch)

    page.process()

    assert controller.state is State.FAILED
    assert controller.banner is not None
    assert controller.banner.text.startswith("No PDF was made. The disk is full. Raw pages kept in")
    assert ".tmp" not in controller.banner.text
    assert controller.can_process_kept
    assert page.pdfs() == []

    page.process()  # room was made: the same pages make the PDF

    assert controller.state is State.DONE
    assert len(page.pdfs()) == 1
    assert not controller.can_process_kept


def test_a_full_disk_in_the_first_run_offers_the_pages_too(
    out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    disk_full_once(monkeypatch)
    page = Page(out, three_pages())
    controller = page.scan()

    assert controller.state is State.FAILED
    assert controller.banner is not None
    assert controller.banner.text.startswith("No PDF was made. The disk is full. Raw pages kept in")
    assert ".tmp" not in controller.banner.text
    assert controller.can_process_kept

    page.process()

    assert controller.state is State.DONE
    assert controller.banner is not None
    assert "went wrong" not in controller.banner.text  # it worked this time
    (pdf,) = page.pdfs()
    assert len(pypdf.PdfReader(pdf).pages) == 3


@pytest.fixture
def read_only(out: Path) -> Iterator[None]:
    yield
    out.chmod(stat.S_IRWXU)  # so that the test folder can be cleaned up


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write to a read-only folder")
@pytest.mark.usefixtures("read_only")
def test_a_read_only_folder_when_the_pages_are_made_keeps_the_way_back(out: Path) -> None:
    page = Page(out, cancelled_after_two())
    controller = page.scan()
    out.chmod(stat.S_IRUSR | stat.S_IXUSR)

    page.process()

    assert controller.state is State.FAILED
    assert controller.banner is not None
    assert controller.banner.text.startswith(
        "No PDF was made. The folder cannot be written to (permission denied). Raw pages kept in"
    )
    assert ".tmp" not in controller.banner.text
    assert controller.can_process_kept

    out.chmod(stat.S_IRWXU)  # the user fixes the permission
    page.process()

    assert controller.state is State.DONE
    assert len(page.pdfs()) == 1
