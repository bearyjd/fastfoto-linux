"""What the README and the design note say about Remove specks is what the code does."""

import re
from pathlib import Path

import pytest

from fastfoto_linux.documents.despeckle_tables import GUARD_UM, SPECK_MAX_UM

ROOT = Path(__file__).resolve().parents[2]
DOCUMENTS = {
    "README": (ROOT / "README.md").read_text(encoding="utf-8"),
    "design note": (ROOT / "docs" / "design" / "documents.md").read_text(encoding="utf-8"),
    "roadmap": (ROOT / "docs" / "roadmaps" / "enhancements.md").read_text(encoding="utf-8"),
}
OCR_CLAIM = re.compile(r"(?i)(improv|better|boost)\w*\s+(the\s+)?ocr|ocr accuracy")


def text_of(name: str) -> str:
    return " ".join(DOCUMENTS[name].split())


@pytest.mark.parametrize("name", ["README", "design note"])
@pytest.mark.parametrize("phrase", ["Remove specks", "off by default", "black and white"])
def test_both_name_the_feature(name: str, phrase: str) -> None:
    assert phrase in text_of(name)


@pytest.mark.parametrize("phrase", ["0.30 mm", "2.5 mm", "format version 5", "--despeckle"])
def test_the_design_note_states_the_numbers_and_the_version(phrase: str) -> None:
    assert phrase in text_of("design note")


def test_the_numbers_are_the_code_s() -> None:
    assert (SPECK_MAX_UM, GUARD_UM) == (300, 2500)


def test_the_readme_names_the_flag() -> None:
    assert "--despeckle" in text_of("README")


def test_the_readme_makes_no_ocr_claim() -> None:
    assert not OCR_CLAIM.search(text_of("README"))
    assert not OCR_CLAIM.search(text_of("design note").split("Despeckle", 1)[-1][:6000])


def test_the_roadmap_moves_despeckle_to_shipped() -> None:
    row = next(line for line in DOCUMENTS["roadmap"].splitlines() if line.startswith("| E06"))
    shipped, open_ = row.split("|")[2], row.split("|")[3]
    assert "despeckle (black and white only, opt-in)" in shipped
    assert "despeckle" not in open_
