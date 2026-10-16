"""``check_settings``: what cannot make a PDF is refused once, for builds and sessions alike."""

from pathlib import Path

import pytest

from fastfoto_linux.documents import (
    DocumentError,
    DocumentSettings,
    DocumentSettingsError,
    OcrMissingError,
    OcrMode,
    build_document,
    check_settings,
)
from tests.documents.helpers import text_scene, write_pages


@pytest.fixture
def out(tmp_path: Path) -> Path:
    root = tmp_path / "out"
    root.mkdir()
    return root


def settings(out: Path, **fields) -> DocumentSettings:
    return DocumentSettings(output_root=out, **{"ocr": OcrMode.OFF, **fields})


@pytest.mark.parametrize("name", ["", "   ", "///", ".."])
def test_a_name_with_no_usable_characters_is_refused(out: Path, name: str) -> None:
    with pytest.raises(DocumentSettingsError, match="name"):
        check_settings(settings(out, name=name))


@pytest.mark.parametrize("langs", ["", "eng;rm", "eng deu", "$(x)"])
def test_languages_that_are_not_tesseract_codes_are_refused(out: Path, langs: str) -> None:
    with pytest.raises(DocumentSettingsError, match="language"):
        check_settings(settings(out, langs=langs))


def test_the_languages_are_checked_even_with_ocr_off(out: Path) -> None:
    with pytest.raises(ValueError, match="language"):
        check_settings(settings(out, langs="eng;rm", ocr=OcrMode.OFF))


def test_ocr_on_without_ocrmypdf_is_refused(out: Path) -> None:
    with pytest.raises(OcrMissingError, match="ocrmypdf"):
        check_settings(settings(out, ocr=OcrMode.ON))


@pytest.mark.parametrize("mode", [OcrMode.AUTO, OcrMode.OFF])
def test_ocr_that_is_not_required_is_never_refused(out: Path, mode: OcrMode) -> None:
    check_settings(settings(out, ocr=mode))


def test_the_refusals_are_document_errors_a_front_end_can_catch(out: Path) -> None:
    for bad in (settings(out, name="///"), settings(out, ocr=OcrMode.ON)):
        with pytest.raises(DocumentError):
            check_settings(bad)


def test_build_document_refuses_a_bad_name_the_same_way_and_writes_nothing(
    tmp_path: Path, out: Path
) -> None:
    pages = write_pages(tmp_path / "raw", [text_scene(1)])
    with pytest.raises(DocumentSettingsError, match="name"):
        build_document(pages, settings(out, name="///"))
    assert list(out.iterdir()) == []
