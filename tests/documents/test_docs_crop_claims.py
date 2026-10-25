"""What the README and the design note say about the manual crop is what the code does."""

from pathlib import Path

import pytest

from fastfoto_linux.documents.draft_json import FORMAT_VERSION

ROOT = Path(__file__).resolve().parents[2]
DOCUMENTS = {
    "README": (ROOT / "README.md").read_text(encoding="utf-8"),
    "design note": (ROOT / "docs" / "design" / "documents.md").read_text(encoding="utf-8"),
}
MAX_README_LINES = 8
MAX_NOTE_LINES = 40


def text_of(name: str) -> str:
    return " ".join(DOCUMENTS[name].split())


@pytest.mark.parametrize("name", list(DOCUMENTS))
def test_the_crop_is_named_with_its_minimum_and_that_nothing_is_analysed_again(name: str) -> None:
    text = text_of(name)
    assert "Crop" in text
    assert "at least 5 mm" in text
    assert "not analysed again" in text


def test_the_design_note_names_the_sidecar_version() -> None:
    assert FORMAT_VERSION == 4
    assert "format version 4" in text_of("design note")


def test_the_manual_crop_section_is_short() -> None:
    lines = DOCUMENTS["design note"].splitlines()
    start = next(
        i for i, line in enumerate(lines) if line.startswith("#") and "Manual crop" in line
    )
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("#")), len(lines))
    assert 0 < end - start <= MAX_NOTE_LINES


def test_the_readme_says_it_in_few_lines() -> None:
    lines = [line for line in DOCUMENTS["README"].splitlines() if "rop" in line]
    assert 0 < len(lines) <= MAX_README_LINES
