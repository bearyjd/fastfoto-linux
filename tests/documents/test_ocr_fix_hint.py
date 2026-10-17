"""What to do about missing OCR is derived from what is missing: Tesseract, OCRmyPDF or both."""

from pathlib import Path

import pytest

from fastfoto_linux.documents import ocr_tools
from fastfoto_linux.documents.ocr_tools import (
    BREW_INSTALL_HINT,
    DNF_INSTALL_HINT,
    OSTREE_NO_BREW_HINT,
    ocr_fix_hint,
    ocr_missing_text,
)
from tests import _fake_ocrmypdf as fake

PIP_HINT = "pip install 'fastfoto-linux[ocr]'"


def machine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, ocrmypdf: bool, tesseract: bool):
    fake.ocr_machine(tmp_path / "bin", monkeypatch, ocrmypdf=ocrmypdf, tesseract=tesseract)


def test_when_only_tesseract_is_missing_the_hint_is_its_install_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    machine(tmp_path, monkeypatch, ocrmypdf=True, tesseract=False)
    assert ocr_missing_text() == "Tesseract is not installed"
    assert ocr_fix_hint() == DNF_INSTALL_HINT


def test_when_only_ocrmypdf_is_missing_the_hint_is_the_installer_or_pip_and_not_tesseract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    machine(tmp_path, monkeypatch, ocrmypdf=False, tesseract=True)
    assert ocr_missing_text() == "OCRmyPDF is not installed"
    hint = ocr_fix_hint()
    assert "installer" in hint
    assert PIP_HINT in hint
    assert "dnf" not in hint
    assert "tesseract" not in hint.lower()


def test_when_both_are_missing_the_hint_gives_both_with_tesseract_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    machine(tmp_path, monkeypatch, ocrmypdf=False, tesseract=False)
    assert ocr_missing_text() == "OCRmyPDF and Tesseract are not installed"
    hint = ocr_fix_hint()
    assert DNF_INSTALL_HINT in hint
    assert PIP_HINT in hint
    assert hint.index(DNF_INSTALL_HINT) < hint.index(PIP_HINT)


def test_the_tesseract_part_follows_the_system(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ostree: None
) -> None:
    machine(tmp_path, monkeypatch, ocrmypdf=False, tesseract=False)
    assert OSTREE_NO_BREW_HINT in ocr_fix_hint()
    assert DNF_INSTALL_HINT not in ocr_fix_hint()


def test_the_tesseract_part_is_brew_where_brew_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, brew_by_name: None
) -> None:
    machine(tmp_path, monkeypatch, ocrmypdf=True, tesseract=False)
    (tmp_path / "bin" / "brew").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (tmp_path / "bin" / "brew").chmod(0o755)
    assert ocr_fix_hint() == BREW_INSTALL_HINT


def test_when_nothing_is_missing_any_more_the_hint_is_still_the_tesseract_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    machine(tmp_path, monkeypatch, ocrmypdf=True, tesseract=True)  # it was installed meanwhile
    assert ocr_fix_hint() == ocr_tools.ocr_install_hint()
