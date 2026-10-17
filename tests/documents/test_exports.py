"""What the documents package offers to its callers, and where the shared words live."""

from pathlib import Path

from fastfoto_linux import documents
from fastfoto_linux.cli import cmd_doc
from fastfoto_linux.documents import ocr
from fastfoto_linux.documents.errors import OutputFolderMissingError
from fastfoto_linux.gui import doctools

HINT = "sudo dnf install ocrmypdf tesseract-osd"


def test_the_one_error_for_a_missing_output_folder_is_exported() -> None:
    assert "OutputFolderMissingError" in documents.__all__
    assert getattr(documents, "OutputFolderMissingError", None) is OutputFolderMissingError


def test_the_ocr_install_hint_lives_with_the_ocr_code() -> None:
    hint = getattr(ocr, "OCR_INSTALL_HINT", None)
    assert hint == HINT


def test_the_command_line_and_the_app_say_the_same_hint() -> None:
    assert cmd_doc.OCR_INSTALL_HINT == HINT
    assert HINT in doctools.NATIVE_OCR_HINT
    assert getattr(ocr, "OCR_INSTALL_HINT", None) == cmd_doc.OCR_INSTALL_HINT


def test_the_app_does_not_reach_into_the_command_line_for_it() -> None:
    source = Path(doctools.__file__).read_text(encoding="utf-8")
    assert "fastfoto_linux.cli" not in source
