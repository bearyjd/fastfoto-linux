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


STALE_GREY_CLAIMS = (
    "backing in 99% of the rows above the strip",  # the column rule: removed in round 5
    "has paper above it",
    "the join to a side is what tells",  # true of colour, not of grey
    "full-height backing beside a receipt",
    "the whole height of the frame",
)


@pytest.mark.parametrize("name", list(DOCUMENTS))
def test_what_a_grey_page_trims_is_described(name: str) -> None:
    text = " ".join(DOCUMENTS[name].split())
    assert "trimmed at the bottom only, never at a side" in text
    assert "the white tail only, never a side" in text
    assert "backing across the whole width" in text
    assert "a grey receipt keeps its tail" in text
    for stale in STALE_GREY_CLAIMS:
        assert stale not in text


@pytest.mark.parametrize("name", ["README", "design note"])
def test_a_colour_page_is_described_as_trimmed_before_it_is_made_grey_or_bw(name: str) -> None:
    text = " ".join(DOCUMENTS[name].split())
    assert "trimmed in colour and only then made grey or black and white" in text


def test_the_design_note_scans_in_colour_whatever_the_output_colour() -> None:
    text = " ".join(DOCUMENTS["design note"].split())
    assert "always `Color`, whatever the output colour" in text
    assert "`Gray` for grey" not in text
    assert "(white tail only; never the sides)" in text


@pytest.mark.parametrize("name", list(DOCUMENTS))
def test_the_blur_of_the_last_check_is_described(name: str) -> None:
    text = " ".join(DOCUMENTS[name].split())
    assert "blurred copy (3x3)" in text


def test_the_bilevel_docstring_states_the_dark_fill_limit() -> None:
    text = " ".join((bilevel.__doc__ or "").split())
    assert "Limit" in text
    assert "darker than DARK_LEVEL" in text
    assert "lost" in text
