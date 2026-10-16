"""What the README and the design note say about ``ffscan doc scan`` is what the command does."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCUMENTS = {
    "README": (ROOT / "README.md").read_text(encoding="utf-8"),
    "design note": (ROOT / "docs" / "design" / "documents.md").read_text(encoding="utf-8"),
}


def text_of(name: str) -> str:
    return " ".join(DOCUMENTS[name].split())


def test_the_readme_shows_the_command() -> None:
    text = text_of("README")
    assert "uv run ffscan doc scan --out" in text
    assert "`--simplex`" in text
    assert "`--keep-raw`" in text
    assert "`--discard-raw`" in text


def test_the_readme_says_the_scan_is_always_in_colour_and_as_long_as_the_page() -> None:
    text = text_of("README")
    assert "`ffscan doc scan` always scans in colour" in text
    assert "whatever `--colour` says" in text
    assert "full length" in text
    assert "200, 300 (default) or 600 dpi" in text


def test_the_readme_says_when_the_raw_pages_are_kept() -> None:
    text = text_of("README")
    assert "`DIR/.raw/<UTC time>/`" in text
    assert "a page was dropped as blank" in text
    assert "searchable text failed" in text
    assert "`--discard-raw` deletes them even then" in text


def test_the_readme_says_what_a_scanner_that_stops_part_way_leaves() -> None:
    text = text_of("README")
    assert "no PDF is made from part of a stack" in text
    assert "ffscan doc process" in text


def test_the_readme_lists_the_exit_codes_of_scanning() -> None:
    text = text_of("README")
    assert "4 the feeder is empty" in text
    assert "130 stopped" in text


def test_the_readme_lists_what_only_the_scanner_can_tell() -> None:
    text = text_of("README")
    assert "Needs the scanner" in text
    for phrase in (
        "the Gray PNG that scanimage writes",
        "trimming on real pages",
        "blank detection on real backs",
        "speed at 300 dpi",
    ):
        assert phrase in text


@pytest.mark.parametrize("name", list(DOCUMENTS))
def test_doc_scan_is_no_longer_described_as_coming_next(name: str) -> None:
    text = text_of(name)
    assert "This first step works on pages you already have" not in text
    assert "`ffscan doc scan`, next, will scan" not in text
    assert "`ffscan doc scan` will always scan in colour" not in text


def test_the_design_note_records_what_the_scan_pull_request_decided() -> None:
    text = text_of("design note")
    assert "## Decisions in `ffscan doc scan` (D2)" in text
    for phrase in (
        "document session",
        "no PDF is made from part of a stack",
        "fallback resolution",
        "`--ocr on` is checked before anything is scanned",
    ):
        assert phrase in text
