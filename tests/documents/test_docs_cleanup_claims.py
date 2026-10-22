"""What the README and the design note say about paper cleanup is what the code does."""

import re
from pathlib import Path

import pytest

from fastfoto_linux.documents import cleanup_tables as tables
from fastfoto_linux.documents.modes import CleanupPolicy

ROOT = Path(__file__).resolve().parents[2]
DOCUMENTS = {
    "README": (ROOT / "README.md").read_text(encoding="utf-8"),
    "design note": (ROOT / "docs" / "design" / "documents.md").read_text(encoding="utf-8"),
}
OCR_CLAIM = re.compile(r"(?i)(improv|better|boost)\w*\s+(the\s+)?ocr|ocr accuracy")


def text_of(name: str) -> str:
    return " ".join(DOCUMENTS[name].split())


@pytest.mark.parametrize("name", list(DOCUMENTS))
def test_the_setting_and_its_three_levels_are_named(name: str) -> None:
    text = text_of(name)
    assert "Paper cleanup" in text
    for label in ("Off", "Light", "Strong"):
        assert label in text
    assert re.search(r"(?i)off by default", text)
    assert [p.value for p in CleanupPolicy] == ["off", "light", "strong"]


@pytest.mark.parametrize("name", list(DOCUMENTS))
def test_black_and_white_and_coloured_paper_are_said_to_be_left_alone(name: str) -> None:
    text = text_of(name)
    assert "black-and-white pages are not changed" in text
    assert "coloured paper is left unchanged" in text


def test_the_design_note_states_the_numbers() -> None:
    text = text_of("design note")
    assert f"{tables.BG_WINDOW_MM:.0f} mm" in text
    for preset in (CleanupPolicy.LIGHT, CleanupPolicy.STRONG):
        gain = tables.PRESETS[preset].max_gain_q / tables.Q
        assert f"{gain:.2f}" in text
    assert "format version 3" in text
    assert "1.10" in text and "1.25" in text


def test_the_readme_makes_no_claim_about_ocr_accuracy() -> None:
    assert OCR_CLAIM.search(text_of("README")) is None
    assert OCR_CLAIM.search(text_of("design note")) is None


def test_the_size_limit_and_the_tone_order_are_stated_as_the_code_has_them() -> None:
    text = text_of("design note")
    assert f"{tables.MAX_WORK_PIXELS // 1_000_000} million pixels" in text
    assert "too_large" in text
    assert "never reversed" in text and "order of tones is kept" not in text
    assert f"{tables.MAX_WORK_PIXELS // 1_000_000} million pixels" in text_of("README")
