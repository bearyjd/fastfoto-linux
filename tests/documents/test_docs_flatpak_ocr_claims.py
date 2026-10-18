"""What the README and the design note say about OCR in the Flatpak is what the manifest builds:
Tesseract with English and page-orientation data, and OCRmyPDF, all inside the bundle."""

import re
from pathlib import Path

import pytest

from fastfoto_linux.documents.ocr_tools import FLATPAK_BROKEN_HINT

ROOT = Path(__file__).resolve().parents[2]
README = " ".join((ROOT / "README.md").read_text(encoding="utf-8").split())
DESIGN = " ".join((ROOT / "docs" / "design" / "documents.md").read_text(encoding="utf-8").split())
BOTH = pytest.mark.parametrize("text", [README, DESIGN], ids=["README", "design note"])
STALE = (
    "will bundle OCR",
    "has no OCR yet",
    "Searchable text needs the native install",
    "Flatpak does not install it yet",
    "No OCR this round",
    "OCR inside the Flatpak (no Tesseract in the runtime yet)",
    "Later: bundle Tesseract",
    "Later: Flatpak OCR",
)


def flatpak_section() -> str:
    match = re.search(r"### Flatpak\b.*?(?=^## |\Z)", (ROOT / "README.md").read_text(), re.M | re.S)
    assert match, "the README has no Flatpak section"
    return " ".join(match.group(0).split())


@BOTH
@pytest.mark.parametrize("phrase", STALE)
def test_nothing_says_the_flatpak_is_still_without_ocr(text: str, phrase: str) -> None:
    assert phrase not in text


def test_the_readme_says_the_flatpak_brings_ocr_with_english_and_orientation_data() -> None:
    section = flatpak_section()
    assert "Tesseract" in section
    assert "OCRmyPDF" in section
    assert "`eng`" in section
    assert "`osd`" in section
    assert "English" in section


def test_the_readme_says_additional_languages_need_explicit_download_then_work_offline() -> None:
    section = flatpak_section().lower()
    assert "english remains bundled" in section
    assert "additional languages" in section
    assert "checkbox picker" in section
    assert "explicitly download the selected missing models" in section
    assert "recognition then works offline" in section
    assert "`--lang eng+deu` works after german has been downloaded" in section
    assert "does not download models during installation or ocr" in section


def test_the_readme_gives_the_flatpak_hint_the_app_shows_when_the_bundle_is_broken() -> None:
    assert FLATPAK_BROKEN_HINT.lower() in README.lower()


def test_the_readme_lists_what_is_bundled_with_its_licences() -> None:
    section = flatpak_section()
    for name, licence in (
        ("Tesseract", "Apache-2.0"),
        ("Leptonica", "BSD-2-Clause"),
        ("tessdata_fast", "Apache-2.0"),
    ):
        assert re.search(rf"{name}[^.;]*{re.escape(licence)}", section), name


def test_the_design_note_says_the_flatpak_bundles_ocr_and_how() -> None:
    assert "tessdata_fast" in DESIGN
    assert "TESSDATA_PREFIX" in DESIGN
    assert "/app/bin" in DESIGN
    assert "requirements-ocr.txt" in DESIGN
