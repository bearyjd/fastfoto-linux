"""What the README and the design note say about getting OCR is what the code does: ocrmypdf
comes with the app, only Tesseract is installed, and the commands are the ones the app shows."""

from pathlib import Path

import pytest

from fastfoto_linux.documents.ocr_tools import (
    BREW_INSTALL_HINT,
    BREW_LANG_HINT,
    DNF_INSTALL_HINT,
    OCR_NEEDS,
    RPM_OSTREE_INSTALL_HINT,
)

ROOT = Path(__file__).resolve().parents[2]
README = " ".join((ROOT / "README.md").read_text(encoding="utf-8").split())
DESIGN = " ".join((ROOT / "docs" / "design" / "documents.md").read_text(encoding="utf-8").split())
STALE = "dnf install ocrmypdf"  # ocrmypdf is no longer an rpm to install
AVAILABLE = f"when OCR is available ({OCR_NEEDS})"


@pytest.mark.parametrize(
    "hint", [BREW_INSTALL_HINT, BREW_LANG_HINT, DNF_INSTALL_HINT, RPM_OSTREE_INSTALL_HINT]
)
def test_the_readme_gives_each_install_command(hint: str) -> None:
    assert f"`{hint}`" in README


@pytest.mark.parametrize("text", [README, DESIGN], ids=["README", "design note"])
def test_nothing_tells_to_install_ocrmypdf_with_dnf(text: str) -> None:
    assert STALE not in text


def test_the_readme_says_ocrmypdf_comes_with_the_app_and_tesseract_does_not() -> None:
    assert "`ocrmypdf` comes with the app" in README
    assert "only Tesseract" in README


def test_the_readme_says_which_system_gets_which_command() -> None:
    assert "Bazzite" in README
    assert "Silverblue" in README
    assert "/run/ostree-booted" in README


def test_the_readme_describes_the_installer_option() -> None:
    assert "--with-tesseract" in README
    assert "never uses `sudo`" in README
    assert "`--uninstall` leaves" in README


def test_the_readme_says_the_flatpak_will_bundle_ocr_later() -> None:
    assert "The Flatpak will bundle OCR in a later release" in README
    assert "The Flatpak build has no OCR yet" not in README


def test_the_design_note_names_the_search_order_and_the_rasterizer() -> None:
    assert "--rasterizer pypdfium" in DESIGN
    assert "linuxbrew" in DESIGN


@pytest.mark.parametrize("text", [README, DESIGN], ids=["README", "design note"])
def test_searchable_text_is_for_where_ocr_is_available_not_where_ocrmypdf_is_installed(
    text: str,
) -> None:
    assert AVAILABLE in text
    assert "when OCRmyPDF is installed" not in text  # Tesseract is needed as well


def test_the_readme_says_an_immutable_system_without_brew_uses_rpm_ostree() -> None:
    assert "without Homebrew" in README
    assert "then reboot" in README


def test_the_readme_says_which_ocrmypdf_uses_pdfium() -> None:
    assert "OCRmyPDF 17 or newer" in README
    assert "pages are rasterized with pdfium" in README.lower()


def test_the_readme_says_the_tesseract_option_is_ignored_when_uninstalling() -> None:
    assert "`--with-tesseract` is ignored with `--uninstall`" in README


def test_the_design_note_says_the_rasterizer_is_for_ocrmypdf_17_and_up() -> None:
    assert "`--rasterizer pypdfium` only for OCRmyPDF 17 or newer" in DESIGN


def test_the_design_note_gives_the_order_of_the_folders_and_when_brews_is_trusted() -> None:
    assert "the PATH it was started with, then the interpreter's folder, then Homebrew's" in DESIGN
    assert "owned by root or by the user" in DESIGN
    assert "not writable by its group or by others" in DESIGN


def test_the_readme_says_what_to_do_when_ocrmypdf_is_the_missing_part() -> None:
    assert "pip install 'fastfoto-linux[ocr]'" in README
    assert "Install OCRmyPDF:" in README
