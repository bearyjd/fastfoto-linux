"""What the design note says about white balance is what the code does."""

import re
from pathlib import Path

from fastfoto_linux.photo_edits import model
from fastfoto_linux.photo_edits.recipe import WHITE_BALANCE_KEYS

ROOT = Path(__file__).resolve().parents[2]
DESIGN = " ".join((ROOT / "docs" / "design" / "photo-white-balance.md").read_text("utf-8").split())
ORDER = "eyes, straighten, crop, quarter turns, white balance, tone"


def test_the_design_note_states_the_ranges_and_neutral() -> None:
    assert model.WB_CONTROL_LIMIT == 100
    for key in sorted(WHITE_BALANCE_KEYS):
        assert f"`{key}`" in DESIGN
    assert f"-{model.WB_CONTROL_LIMIT} to {model.WB_CONTROL_LIMIT}" in DESIGN
    assert "neutral 0" in DESIGN


def test_the_design_note_states_the_schema_and_algorithm() -> None:
    assert f"schema {model.WHITE_BALANCE_SCHEMA_VERSION}" in DESIGN
    assert f"`{model.WHITE_BALANCE_ALGORITHM_VERSION}`" in DESIGN
    assert model.RECIPE_VERSIONS[model.WHITE_BALANCE_SCHEMA_VERSION] == "photo-color-v1"


def test_the_order_string_is_in_every_doc_that_names_the_order() -> None:
    for name in ("photo-white-balance.md", "photo-geometry.md"):
        text = " ".join((ROOT / "docs" / "design" / name).read_text("utf-8").split())
        assert ORDER in text, name
    tone = " ".join((ROOT / "docs" / "design" / "photo-tone.md").read_text("utf-8").split())
    assert re.search(r"red-eye correction and white balance", tone)


def test_the_design_note_names_its_limits() -> None:
    for phrase in ("sRGB", "clip", "uint8", "synthetic"):
        assert phrase in DESIGN
