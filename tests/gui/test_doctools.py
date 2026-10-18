"""What the Documents form needs to know about OCRmyPDF and the sandbox."""

from pathlib import Path

import pytest

from fastfoto_linux.documents import ocr_tools
from fastfoto_linux.gui.doctools import (
    FLATPAK_OCR_HINT,
    NATIVE_OCR_HINT,
    DocumentTools,
)
from tests import _fake_ocrmypdf as fake

pytestmark = pytest.mark.usefixtures("ocrmypdf_comes_with_the_app")


def tools(*, found: str | None, flatpak: bool) -> DocumentTools:
    return DocumentTools(find_ocr=lambda: found, in_flatpak=lambda: flatpak)


def test_the_hints_say_what_to_install_or_that_the_flatpak_is_broken() -> None:
    assert NATIVE_OCR_HINT == "Install Tesseract: sudo dnf install tesseract tesseract-osd"
    assert FLATPAK_OCR_HINT == ocr_tools.FLATPAK_BROKEN_HINT
    assert "reinstall" in FLATPAK_OCR_HINT.lower()


@pytest.mark.parametrize("command", ["brew", "rpm-ostree", "dnf", "native install"])
def test_the_flatpak_hint_sends_nobody_to_install_anything_from_outside(command: str) -> None:
    assert command not in FLATPAK_OCR_HINT.lower()


def test_missing_ocr_on_an_immutable_system_without_brew_says_rpm_ostree_or_homebrew(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / "ostree-booted"
    marker.touch()
    monkeypatch.setattr(ocr_tools, "OSTREE_MARKER", marker)
    missing = tools(found=None, flatpak=False)
    assert missing.ocr_hint == "Install Tesseract: " + ocr_tools.OSTREE_NO_BREW_HINT


def test_missing_ocr_where_brew_runs_says_to_use_homebrew(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "bin"
    folder.mkdir()
    (folder / "brew").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (folder / "brew").chmod(0o755)
    monkeypatch.setenv("PATH", str(folder))
    monkeypatch.setattr(ocr_tools, "BREW", "brew")
    missing = tools(found=None, flatpak=False)
    assert missing.ocr_hint == "Install Tesseract: brew install tesseract"


def test_ocr_that_is_found_is_available_and_needs_no_hint() -> None:
    found = tools(found="/usr/bin/ocrmypdf", flatpak=False)
    assert found.ocr_available is True
    assert found.ocr_hint == ""


def test_missing_ocr_on_the_desktop_says_how_to_install_it() -> None:
    missing = tools(found=None, flatpak=False)
    assert missing.ocr_available is False
    assert missing.ocr_hint == NATIVE_OCR_HINT


def test_missing_ocr_in_the_flatpak_says_the_bundle_is_broken() -> None:
    missing = tools(found=None, flatpak=True)
    assert missing.ocr_available is False
    assert missing.ocr_hint == FLATPAK_OCR_HINT


def test_ocr_found_in_the_flatpak_is_used_without_a_hint() -> None:
    found = tools(found="/app/bin/ocrmypdf", flatpak=True)
    assert (found.ocr_available, found.ocr_hint) == (True, "")


def test_the_defaults_look_at_the_real_machine_without_failing() -> None:
    real = DocumentTools()
    assert isinstance(real.ocr_available, bool)
    assert real.ocr_hint == ("" if real.ocr_available else real.ocr_hint)


def test_missing_tesseract_alone_says_to_install_tesseract_and_not_ocrmypdf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake.ocr_machine(tmp_path / "bin", monkeypatch, ocrmypdf=True, tesseract=False)
    hint = tools(found=None, flatpak=False).ocr_hint
    assert hint == NATIVE_OCR_HINT
    assert "OCRmyPDF" not in hint


def test_missing_ocrmypdf_alone_says_to_run_the_installer_or_pip_and_not_to_install_tesseract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake.ocr_machine(tmp_path / "bin", monkeypatch, ocrmypdf=False, tesseract=True)
    hint = tools(found=None, flatpak=False).ocr_hint
    assert hint.startswith("Install OCRmyPDF: ")
    assert "installer" in hint
    assert "pip install 'fastfoto-linux[ocr]'" in hint
    assert "Tesseract" not in hint
    assert "dnf" not in hint


def test_missing_ocrmypdf_and_tesseract_says_both_with_tesseract_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake.ocr_machine(tmp_path / "bin", monkeypatch, ocrmypdf=False, tesseract=False)
    hint = tools(found=None, flatpak=False).ocr_hint
    assert NATIVE_OCR_HINT in hint
    assert "Install OCRmyPDF: " in hint
    assert "pip install 'fastfoto-linux[ocr]'" in hint
    assert hint.index(NATIVE_OCR_HINT) < hint.index("Install OCRmyPDF: ")


def test_the_flatpak_hint_does_not_depend_on_which_part_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake.ocr_machine(tmp_path / "bin", monkeypatch, ocrmypdf=False, tesseract=False)
    assert tools(found=None, flatpak=True).ocr_hint == FLATPAK_OCR_HINT
