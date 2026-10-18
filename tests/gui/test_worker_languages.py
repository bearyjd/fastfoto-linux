"""Missing OCR models are refused before scanner discovery or feeding, off the UI thread."""

import threading
from pathlib import Path

import pytest

from fastfoto_linux.documents import OcrMissingError
from fastfoto_linux.gui.docform import DocumentForm
from fastfoto_linux.gui.doctools import DocumentTools
from fastfoto_linux.gui.worker import Worker
from fastfoto_linux.scanner import ScanTarget
from tests.cli.fakes import DEVICE
from tests.gui.doc_helpers import DocRecordingSink, FakeBuild, ScriptedDocumentSession

WAIT = 5.0


@pytest.mark.parametrize("searchable", [False, True])
def test_worker_checks_models_before_any_scanner_access(out: Path, searchable: bool) -> None:
    sink = DocRecordingSink()
    session = ScriptedDocumentSession(out)
    calls: list[tuple[str, int]] = []

    def check(langs: str) -> None:
        calls.append((langs, threading.get_ident()))
        raise OcrMissingError("Download Spanish (spa) before scanning.")

    def discover() -> ScanTarget:
        calls.append(("scanner", threading.get_ident()))
        return ScanTarget(device=DEVICE)

    tools = DocumentTools(session=session, build=FakeBuild(out), check_languages=check)
    worker = Worker(sink, discover=discover, documents=tools)
    worker.scan_documents(
        DocumentForm(langs="spa", searchable=searchable), str(out), ocr_available=True
    )
    assert sink.finished.wait(WAIT)
    worker.join(WAIT)
    if searchable:
        assert [call for call, _ in calls] == ["spa"]
        assert calls[0][1] != threading.get_ident()
        assert session.requests == []
        assert isinstance(sink.events[-1][1], OcrMissingError)
    else:
        assert [call for call, _ in calls] == ["scanner"]
        assert len(session.requests) == 1
