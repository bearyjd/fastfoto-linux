"""What the README and the design note say about fold creases and about loading the feeder."""

from pathlib import Path

import pytest

from fastfoto_linux.documents import marks

ROOT = Path(__file__).resolve().parents[2]
DOCUMENTS = {
    "README": (ROOT / "README.md").read_text(encoding="utf-8"),
    "design note": (ROOT / "docs" / "design" / "documents.md").read_text(encoding="utf-8"),
}


def text_of(name: str) -> str:
    return " ".join(DOCUMENTS[name].split())


@pytest.mark.parametrize("name", list(DOCUMENTS))
def test_the_blank_rule_is_described_as_ignoring_faint_fold_creases(name: str) -> None:
    text = text_of(name)
    assert "faint fold creases" in text
    assert "line-like and faint" in text
    assert "0.6 mm" in text
    assert "8 times" in text
    assert "140" in text


@pytest.mark.parametrize("name", list(DOCUMENTS))
def test_the_limit_of_the_crease_rule_is_described(name: str) -> None:
    text = text_of(name)
    assert "a single faint pencil stroke" in text
    assert "dust" in text
    assert "touching a crease" in text


@pytest.mark.parametrize("name", list(DOCUMENTS))
def test_the_loading_of_the_feeder_is_described(name: str) -> None:
    text = text_of(name)
    assert "face down, top edge first" in text
    assert "printed side is then scanned first" in text
    assert "checked on the FF-680W" in text


def test_the_scanners_png_is_described_as_carrying_its_resolution() -> None:
    design = text_of("design note")
    assert "carries its resolution" in text_of("README")
    assert "carries its resolution" in design
    assert "fallback resolution" in design  # kept for files that do not say
    assert "whether the PNG header carries" not in design
    assert "could not be checked without the scanner" not in design


def test_the_marks_module_documents_the_crease_rule() -> None:
    text = " ".join((marks.__doc__ or "").split())
    assert "fold crease" in text
