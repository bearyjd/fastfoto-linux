"""What the design note says about detail is what the code does."""

import re
from pathlib import Path

from fastfoto_linux.photo_edits import detail, model
from fastfoto_linux.photo_edits.recipe import DETAIL_KEYS

ROOT = Path(__file__).resolve().parents[2]
ORDER = "eyes, denoise, straighten, crop, quarter turns, white balance, tone, sharpen"


def _doc(name: str) -> str:
    return " ".join((ROOT / "docs" / "design" / name).read_text("utf-8").split())


DESIGN = _doc("photo-detail.md")


def test_the_design_note_states_the_ranges_and_neutral() -> None:
    assert model.DETAIL_CONTROL_LIMIT == 100
    for key in sorted(DETAIL_KEYS):
        assert f"`{key}`" in DESIGN
    assert f"0 to {model.DETAIL_CONTROL_LIMIT}" in DESIGN
    assert "neutral 0" in DESIGN


def test_the_design_note_states_the_schema_and_algorithm() -> None:
    assert f"schema {model.DETAIL_SCHEMA_VERSION}" in DESIGN
    assert f"`{model.DETAIL_ALGORITHM_VERSION}`" in DESIGN
    assert model.RECIPE_VERSIONS[model.DETAIL_SCHEMA_VERSION] == "photo-detail-v1"


def test_the_design_note_states_the_math_constants() -> None:
    assert f"template window {detail.NLM_TEMPLATE}" in DESIGN
    assert f"search window {detail.NLM_SEARCH}" in DESIGN
    assert f"halo of {detail.DENOISE_HALO} rows" in DESIGN
    assert f"`H_LUMA_MAX` = {detail.H_LUMA_MAX:g}" in DESIGN
    assert f"`H_CHROMA_MAX` = {detail.H_CHROMA_MAX:g}" in DESIGN
    assert f"amount = {detail.SHARPEN_AMOUNT_MAX:g} * sharpen / 100" in DESIGN
    assert "sigma = clamp(effective_dpi / 300, 0.5, 3.0)" in DESIGN
    assert f"`DETAIL_BAND_PIXELS` = {detail.DETAIL_BAND_PIXELS}" in DESIGN


def test_the_order_string_is_in_every_doc_that_names_the_order() -> None:
    for name in ("photo-detail.md", "photo-white-balance.md", "photo-geometry.md"):
        assert ORDER in _doc(name), name
    assert re.search(r"denoise.*sharpen", _doc("photo-tone.md"))


def test_the_design_note_names_its_limits() -> None:
    for phrase in (
        "synthetic",
        "uncalibrated",
        "halos",
        "no stage cache",
        "grain",
        "full resolution",
    ):
        assert phrase in DESIGN


def test_the_cost_table_names_both_resolutions() -> None:
    assert re.search(r"\| 4x6 in at 300 dpi ", DESIGN)
    assert re.search(r"\| 4x6 in at 600 dpi ", DESIGN)
    assert re.search(r"\| 8x10 in at 600 dpi ", DESIGN)
    assert "OpenCV" in DESIGN
