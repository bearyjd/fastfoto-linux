"""What the README and the design note say about the Documents mode of the app is what it does."""

import errno
import re
from pathlib import Path

from fastfoto_linux.gui.controller import PROCESS_KEPT_TEXT
from fastfoto_linux.gui.docform import DOCUMENT_COLOURS, DocumentForm
from fastfoto_linux.gui.docreport import document_error_banner
from fastfoto_linux.gui.doctools import FLATPAK_OCR_HINT, NATIVE_OCR_HINT
from fastfoto_linux.session import DOCUMENT_DPI

ROOT = Path(__file__).resolve().parents[2]
README = (ROOT / "README.md").read_text(encoding="utf-8")
DESIGN = (ROOT / "docs" / "design" / "documents.md").read_text(encoding="utf-8")


def desktop_section() -> str:
    match = re.search(r"^## Desktop app \(preview\).*?(?=^### Flatpak)", README, re.M | re.S)
    assert match, "the README has no Desktop app section"
    return " ".join(match.group(0).split())


def test_the_readme_gives_the_install_hint_the_app_shows() -> None:
    assert NATIVE_OCR_HINT in desktop_section()
    assert FLATPAK_OCR_HINT.lower() in desktop_section().lower()


def test_the_readme_lists_the_resolutions_and_the_default() -> None:
    section = desktop_section()
    assert " / ".join(map(str, DOCUMENT_DPI)) + " dpi" in section
    assert f"({DocumentForm().dpi} is the default)" in section


def test_the_readme_names_the_colours_the_form_offers() -> None:
    section = desktop_section()
    assert len(DOCUMENT_COLOURS) == 4
    assert "Auto / Colour / Grey / Black and white" in section


def test_the_readme_names_the_button_for_kept_pages() -> None:
    assert f"**{PROCESS_KEPT_TEXT}**" in desktop_section()


def test_the_readme_says_the_flatpak_has_the_ocr_built_in() -> None:
    assert "In the Flatpak the OCR is built in" in desktop_section()
    assert "The Flatpak has no OCR yet" not in desktop_section()


def test_the_design_note_has_the_decisions_of_the_desktop_app() -> None:
    assert "## Decisions in the desktop app (D3)" in DESIGN
    assert "later PR" not in DESIGN.split("## Flatpak")[0].split("## Desktop app")[-1]


def test_the_readme_no_longer_says_the_documents_mode_is_to_come() -> None:
    assert "comes next" not in README


def test_the_design_note_words_the_raw_folder_error_as_the_app_does() -> None:
    banner = document_error_banner(OSError(errno.EACCES, "Permission denied", "/out/.raw"))
    assert banner.text.startswith("The scan failed.")
    decisions = " ".join(DESIGN.split("## Decisions in the desktop app (D3)")[-1].split())
    assert 'an `OSError` for the raw folder as "The scan failed.' in decisions
