"""What the README and the design note say about editing a document and several PDFs is what
``ffscan doc process`` does."""

from pathlib import Path

import pytest

from fastfoto_linux.cli import doc_edit_options
from fastfoto_linux.documents import write

ROOT = Path(__file__).resolve().parents[2]
DOCUMENTS = {
    "README": (ROOT / "README.md").read_text(encoding="utf-8"),
    "design note": (ROOT / "docs" / "design" / "documents.md").read_text(encoding="utf-8"),
}


def text_of(name: str) -> str:
    return " ".join(DOCUMENTS[name].split())


@pytest.mark.parametrize("name", list(DOCUMENTS))
def test_every_edit_option_is_described(name: str) -> None:
    text = text_of(name)
    for option in doc_edit_options.EDIT_OPTIONS:
        assert f"`{option}" in text, option


def test_the_readme_shows_the_edits_with_examples() -> None:
    text = text_of("README")
    assert "--drop 2,4" in text
    assert "--rotate 3:90" in text
    assert "--split 5,9" in text
    assert "--part-name" in text
    assert "--dry-run" in text


@pytest.mark.parametrize("name", list(DOCUMENTS))
def test_the_angles_are_the_ones_the_option_takes(name: str) -> None:
    text = text_of(name)
    angles = ", ".join(str(angle) for angle in doc_edit_options.ANGLES)
    assert f"clockwise {angles.replace(', 270', ' or 270')}" in text


@pytest.mark.parametrize("name", list(DOCUMENTS))
def test_the_part_name_rules_are_described(name: str) -> None:
    text = text_of(name)
    assert write.PART_NAME_TEMPLATE.format(name="NAME", number="N") in text
    assert "its own next number" in text
    assert "all parts or none" in text
    assert "the PDF's title" in text


@pytest.mark.parametrize("name", list(DOCUMENTS))
def test_the_limits_are_described(name: str) -> None:
    text = text_of(name)
    assert "--rotate-pages" in text
    assert "may turn a page back" in text
    assert "left as they were" in text
