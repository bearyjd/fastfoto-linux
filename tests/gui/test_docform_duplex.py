"""The Documents form pairs the pages as sheets exactly when it scans both sides."""

from pathlib import Path

import pytest

from fastfoto_linux.gui.docform import DocumentForm, to_document_request, to_document_settings
from fastfoto_linux.scanner import ScanTarget
from tests.cli.fakes import DEVICE

TARGET = ScanTarget(device=DEVICE)


@pytest.mark.parametrize("both_sides", [True, False])
def test_the_settings_pair_the_pages_when_both_sides_are_scanned(
    tmp_path: Path, both_sides: bool
) -> None:
    settings = to_document_settings(
        DocumentForm(both_sides=both_sides), tmp_path, ocr_available=False
    )
    assert settings.duplex is both_sides


@pytest.mark.parametrize("both_sides", [True, False])
def test_the_request_scans_and_pairs_the_same_way(tmp_path: Path, both_sides: bool) -> None:
    request = to_document_request(
        DocumentForm(both_sides=both_sides), str(tmp_path), TARGET, ocr_available=False
    )
    assert request.duplex is both_sides
    assert request.settings.duplex is both_sides
