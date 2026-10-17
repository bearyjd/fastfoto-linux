"""A document scan and the pairing of its pages must agree: a one-sided scan is never paired."""

from dataclasses import replace
from pathlib import Path

import pytest

from fastfoto_linux.documents import DocumentSettings, OcrMode
from fastfoto_linux.scanner import ScanTarget
from fastfoto_linux.session import DocumentScanRequest
from tests.cli.fakes import DEVICE
from tests.documents.helpers import text_scene
from tests.session.doc_session_helpers import make_doc_request, run_doc


@pytest.fixture
def out(tmp_path: Path) -> Path:
    folder = tmp_path / "out"
    folder.mkdir()
    return folder


@pytest.mark.parametrize("scan_duplex", [True, False])
def test_a_request_whose_settings_pair_the_pages_the_other_way_is_refused(
    out: Path, scan_duplex: bool
) -> None:
    with pytest.raises(ValueError, match="paired wrongly"):
        DocumentScanRequest(
            target=ScanTarget(device=DEVICE),
            settings=DocumentSettings(output_root=out, ocr=OcrMode.OFF, duplex=not scan_duplex),
            duplex=scan_duplex,
        )


def test_the_default_request_scans_both_sides_and_pairs_them(out: Path) -> None:
    request = DocumentScanRequest(
        target=ScanTarget(device=DEVICE), settings=DocumentSettings(output_root=out)
    )
    assert (request.duplex, request.settings.duplex) == (True, True)


def test_a_changed_request_cannot_unpair_a_duplex_scan(out: Path) -> None:
    request = make_doc_request(out, duplex=True)
    with pytest.raises(ValueError, match="paired wrongly"):
        replace(request, settings=replace(request.settings, duplex=False))


@pytest.mark.parametrize("duplex", [True, False])
def test_the_session_builds_the_document_with_the_pairing_of_the_scan(
    out: Path, doc_transport, duplex: bool
) -> None:
    seen: list[bool] = []

    def build(pages, settings, *, cancel=None):
        seen.append(settings.duplex)
        raise RuntimeError("stop here")

    doc_transport.scenes = [text_scene(1)]
    request = make_doc_request(out, duplex=duplex, dpi=300)
    run_doc(request, doc_transport, build=build)
    assert seen == [duplex]
