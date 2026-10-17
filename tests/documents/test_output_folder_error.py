"""One missing output folder is one error with one message, wherever it is found."""

from pathlib import Path
from typing import Any

import pytest

from fastfoto_linux.documents import (
    DocumentSettings,
    DocumentSettingsError,
    OcrMode,
    build,
    build_document,
    check_settings,
)
from fastfoto_linux.documents.publish import publish_pdf
from fastfoto_linux.output.errors import OutputRootMissingError
from fastfoto_linux.session import run_document_session
from tests.documents.helpers import text_scene, write_pages
from tests.session.doc_session_helpers import make_doc_request


def settings(folder: Path) -> DocumentSettings:
    return DocumentSettings(output_root=folder, ocr=OcrMode.OFF)


def message_with(error: BaseException, folder: Path) -> str:
    """The message with the folder's path taken out, to compare the wording."""
    return str(error).replace(str(folder), "<folder>")


def test_building_into_a_missing_folder_is_a_settings_error(tmp_path: Path) -> None:
    gone = tmp_path / "gone"
    pages = write_pages(tmp_path, [text_scene(1)])
    with pytest.raises(DocumentSettingsError, match="gone"):
        build_document(pages, settings(gone))
    assert not gone.exists()


def test_a_missing_folder_is_found_before_a_single_page_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("a page was read before the output folder was checked")

    monkeypatch.setattr(build, "inspect_page", refuse)
    pages = write_pages(tmp_path, [text_scene(1)])
    with pytest.raises(DocumentSettingsError):
        build_document(pages, settings(tmp_path / "gone"))


def test_a_file_where_the_folder_should_be_is_the_same_error(tmp_path: Path) -> None:
    file = tmp_path / "file.txt"
    file.write_text("not a folder")
    with pytest.raises(DocumentSettingsError, match=r"file\.txt"):
        check_settings(settings(file))


def test_publishing_into_a_missing_folder_is_both_kinds_of_error(tmp_path: Path) -> None:
    """The one error is a settings error, and still the output error older callers catch."""
    with pytest.raises(DocumentSettingsError):
        publish_pdf(b"%PDF", tmp_path / "gone", "Document")
    with pytest.raises(OutputRootMissingError):
        publish_pdf(b"%PDF", tmp_path / "gone", "Document")


def test_the_session_and_the_build_say_it_the_same_way(tmp_path: Path) -> None:
    gone = tmp_path / "gone"
    pages = write_pages(tmp_path, [text_scene(1)])
    with pytest.raises(DocumentSettingsError) as from_build:
        build_document(pages, settings(gone))
    with pytest.raises(DocumentSettingsError) as from_session:
        run_document_session(make_doc_request(gone))
    assert type(from_build.value) is type(from_session.value)
    assert message_with(from_build.value, gone) == message_with(from_session.value, gone)
    assert "gone" in str(from_build.value)
