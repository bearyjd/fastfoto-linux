"""What the Documents form needs to know about OCRmyPDF and the sandbox."""

from fastfoto_linux.gui.doctools import (
    FLATPAK_OCR_HINT,
    NATIVE_OCR_HINT,
    DocumentTools,
)


def tools(*, found: str | None, flatpak: bool) -> DocumentTools:
    return DocumentTools(find_ocr=lambda: found, in_flatpak=lambda: flatpak)


def test_the_hints_say_what_to_install_or_that_the_native_install_is_needed() -> None:
    assert NATIVE_OCR_HINT == "Install OCRmyPDF: sudo dnf install ocrmypdf tesseract-osd"
    assert FLATPAK_OCR_HINT == "Searchable text needs the native install"


def test_ocr_that_is_found_is_available_and_needs_no_hint() -> None:
    found = tools(found="/usr/bin/ocrmypdf", flatpak=False)
    assert found.ocr_available is True
    assert found.ocr_hint == ""


def test_missing_ocr_on_the_desktop_says_how_to_install_it() -> None:
    missing = tools(found=None, flatpak=False)
    assert missing.ocr_available is False
    assert missing.ocr_hint == NATIVE_OCR_HINT


def test_missing_ocr_in_the_flatpak_says_it_needs_the_native_install() -> None:
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
