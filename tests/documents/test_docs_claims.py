"""What the README, the design note and the docstrings say about trimming and the black-and-white
limit is what the code does: it cuts only what is certainly empty, and says what it cannot read."""

from pathlib import Path

import pytest

from fastfoto_linux.documents import bilevel, trim

ROOT = Path(__file__).resolve().parents[2]
DOCUMENTS = {
    "README": (ROOT / "README.md").read_text(encoding="utf-8"),
    "design note": (ROOT / "docs" / "design" / "documents.md").read_text(encoding="utf-8"),
    "trim docstring": trim.__doc__ or "",
}


@pytest.mark.parametrize("name", list(DOCUMENTS))
def test_trimming_is_described_as_cutting_only_what_is_certainly_empty(name: str) -> None:
    text = " ".join(DOCUMENTS[name].split())
    assert "certainly empty" in text
    assert "certainly not paper" not in text


@pytest.mark.parametrize("name", list(DOCUMENTS))
def test_the_last_check_on_every_cut_strip_is_described(name: str) -> None:
    text = " ".join(DOCUMENTS[name].split())
    assert "neither blank white nor backing" in text


def test_the_bilevel_docstring_states_the_dark_fill_limit() -> None:
    text = " ".join((bilevel.__doc__ or "").split())
    assert "Limit" in text
    assert "darker than DARK_LEVEL" in text
    assert "lost" in text
