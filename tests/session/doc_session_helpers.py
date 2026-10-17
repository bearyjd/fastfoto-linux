"""Builders for the document session tests."""

from pathlib import Path
from typing import Any

from fastfoto_linux.documents import ColourMode, DocumentSettings, OcrMode
from fastfoto_linux.scanner import ScanTarget
from fastfoto_linux.session import DocumentScanRequest, RawPolicy, run_document_session
from tests.cli.fakes import DEVICE
from tests.documents.scan_fakes import DocTransport


def make_doc_request(  # noqa: PLR0913
    out: Path,
    *,
    policy: RawPolicy = RawPolicy.AUTO,
    dpi: int = 300,
    duplex: bool = True,
    raw_parent: Path | None = None,
    colour: ColourMode = ColourMode.COLOUR,
    **settings: Any,
) -> DocumentScanRequest:
    """A request for a duplex batch into ``out`` without searchable text unless overridden."""
    document = DocumentSettings(
        output_root=out, colour=colour, duplex=duplex, **{"ocr": OcrMode.OFF, **settings}
    )
    return DocumentScanRequest(
        target=ScanTarget(device=DEVICE),
        settings=document,
        dpi=dpi,
        duplex=duplex,
        raw_policy=policy,
        raw_parent=raw_parent,
    )


def run_doc(request: DocumentScanRequest, transport: DocTransport, **options: Any):
    """``run_document_session`` with the fake scanner transport."""
    return run_document_session(request, scan=transport.run_scan, **options)
