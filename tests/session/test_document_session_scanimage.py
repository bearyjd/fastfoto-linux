"""``run_document_session`` over the real runner and a fake ``scanimage`` (a real subprocess)
that writes real PNG pages from synthetic documents."""

import json
import threading
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from fastfoto_linux.scanner import run_scan
from fastfoto_linux.session import (
    DocumentRawReason,
    RawPolicy,
    Stage,
    run_document_session,
)
from tests._fake_scanimage import fake_env, install
from tests.documents.helpers import blank_scene, reader, text_scene, write_pages
from tests.session.conftest import STAMP, kept_names
from tests.session.doc_session_helpers import make_doc_request

pytestmark = pytest.mark.usefixtures("no_real_ocr")

SCAN_TIMEOUT_S = 20.0  # a scan that is not stopped gives up instead of hanging the suite
CANCEL_DELAY_S = 0.2
PAGE_DELAY_S = 0.4
SOURCE_DPI = 100


@pytest.fixture
def fake_scanimage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[..., Path]:
    """Make the next scan run the fake ``scanimage`` told to behave as ``spec`` says; the
    result is the file that receives its argv."""

    def configure(**spec: Any) -> Path:
        record = tmp_path / "scanimage.json"
        bin_dir = install(tmp_path / "bin")
        for name, value in fake_env(bin_dir, record_to=str(record), **spec).items():
            monkeypatch.setenv(name, value)
        return record

    return configure


def real_scan() -> Callable[..., Any]:
    return partial(run_scan, timeout_s=SCAN_TIMEOUT_S)


def source_files(tmp_path: Path, scenes: list) -> list[str]:
    return [str(path) for path in write_pages(tmp_path / "sources", scenes)]


def argv_after(record: Path, flag: str) -> str:
    argv = json.loads(record.read_text())["argv"]
    return argv[argv.index(flag) + 1]


def test_pages_from_the_scanner_become_a_pdf_and_the_blank_one_is_dropped(
    out, tmp_path, fake_scanimage
) -> None:
    record = fake_scanimage(
        page_sources=source_files(tmp_path, [text_scene(1), blank_scene(2), text_scene(3)])
    )
    result = run_document_session(
        make_doc_request(out, dpi=200, policy=RawPolicy.KEEP), scan=real_scan()
    )
    assert result.ok
    assert result.pages_scanned == 3
    assert result.document is not None
    assert result.document.dropped == (2,)
    assert len(reader(result.document.pdf.read_bytes()).pages) == 2
    assert argv_after(record, "--mode") == "Color"
    assert argv_after(record, "--resolution") == "200"
    assert argv_after(record, "--source") == "ADF Duplex"
    with Image.open(result.kept_pages[0]) as page:  # what scanimage delivered: colour, 200 dpi
        assert page.mode == "RGB"
        assert round(page.info["dpi"][0]) == 200


def test_a_simplex_scan_asks_for_the_front_only(out, tmp_path, fake_scanimage) -> None:
    record = fake_scanimage(page_sources=source_files(tmp_path, [text_scene(1)]))
    result = run_document_session(make_doc_request(out, duplex=False), scan=real_scan())
    assert result.ok
    assert argv_after(record, "--source") == "ADF Front"


def test_pages_without_a_resolution_are_taken_at_the_one_asked_for(
    out, tmp_path, fake_scanimage
) -> None:
    fake_scanimage(page_sources=source_files(tmp_path, [text_scene(1)]), no_dpi=True)
    result = run_document_session(make_doc_request(out, dpi=200), scan=real_scan())
    assert result.ok  # without the fallback the page would be refused for not saying its dpi
    width = float(reader(result.document.pdf.read_bytes()).pages[0].mediabox.width)
    assert width == pytest.approx(850 * 2 * 72 / 200, abs=0.5)  # 850 px at 100 dpi, made 200 dpi


def test_a_cancel_from_another_thread_stops_scanimage_and_makes_no_pdf(
    out, tmp_path, fake_scanimage
) -> None:
    marker = tmp_path / "sigterm-marker"
    fake_scanimage(
        page_sources=source_files(tmp_path, [text_scene(1), text_scene(2), text_scene(3)]),
        page_delay_s=PAGE_DELAY_S,
        hang=True,
        sigterm_marker=str(marker),
    )
    cancel = threading.Event()
    canceller = threading.Timer(CANCEL_DELAY_S, cancel.set)
    stages: list[Stage] = []
    pages: list[int] = []

    def on_page(number: int) -> None:
        pages.append(number)
        if number == 1:
            canceller.start()  # the first page is down: now somebody presses Cancel

    try:
        result = run_document_session(
            make_doc_request(out, dpi=200, policy=RawPolicy.DISCARD),
            scan=real_scan(),
            cancel=cancel,
            on_page=on_page,
            on_stage=stages.append,
        )
    finally:
        canceller.cancel()
    assert marker.read_text() == "terminated"  # scanimage was stopped, not left scanning
    assert result.cancelled
    assert result.error is None
    assert result.document is None
    assert result.raw_reason is DocumentRawReason.CANCELLED
    assert result.raw_dir == out / ".raw" / STAMP
    assert kept_names(result.raw_dir)[0] == "page-0001.png"
    assert pages[0] == 1
    assert stages == [Stage.SCANNING, Stage.DONE]
    assert not [p for p in out.iterdir() if p.suffix == ".pdf"]
