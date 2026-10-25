"""What the README and the design note say about ``--cleanup`` and the stored crop on the
command line is what the code does."""

import re
from pathlib import Path

import pytest

from fastfoto_linux.documents.modes import CleanupPolicy

ROOT = Path(__file__).resolve().parents[2]
DOCUMENTS = {
    "README": (ROOT / "README.md").read_text(encoding="utf-8"),
    "design note": (ROOT / "docs" / "design" / "documents.md").read_text(encoding="utf-8"),
}
LEVELS = "|".join(policy.value for policy in CleanupPolicy)
OCR_CLAIM = re.compile(r"(?i)(improv|better|boost)\w*\s+(the\s+)?ocr|ocr accuracy")


def text_of(name: str) -> str:
    return " ".join(DOCUMENTS[name].split())


@pytest.mark.parametrize("name", list(DOCUMENTS))
def test_the_flag_and_its_three_levels_are_named(name: str) -> None:
    assert f"--cleanup {LEVELS}" in text_of(name)


def test_the_readme_says_which_commands_take_the_flag() -> None:
    text = text_of("README")
    assert re.search(
        r"`--cleanup [a-z|]+` sets the level for `ffscan doc scan` and `doc process`", text
    )


def test_the_readme_says_what_doc_process_does_without_the_flag() -> None:
    text = text_of("README")
    assert re.search(r"without it, `doc process` applies the level a review file holds", text)
    assert re.search(r"a page's own (level|override) in the review file (still )?wins", text)


def test_the_readme_example_uses_the_flag() -> None:
    lines = DOCUMENTS["README"].splitlines()
    assert any(
        line.startswith("uv run ffscan doc process") and "--cleanup light" in line for line in lines
    )


def test_the_readme_says_process_applies_a_stored_crop_and_fresh_ignores_it() -> None:
    text = text_of("README")
    assert "there is no command-line option to set one" in text
    assert "`ffscan doc process RAWDIR` applies a stored crop (`--fresh` ignores it)" in text
    assert "there is no command-line option for it" not in text


def test_the_design_note_describes_the_flag_on_the_command_line() -> None:
    text = text_of("design note")
    assert "keeps Off" not in text
    assert re.search(r"\[--cleanup [a-z|]+\]", text)
    assert "`--cleanup` is a document option of both commands" in text
    assert "`--fresh` ignores" in text


@pytest.mark.parametrize("name", list(DOCUMENTS))
def test_no_claim_is_made_about_ocr_accuracy(name: str) -> None:
    assert OCR_CLAIM.search(text_of(name)) is None
