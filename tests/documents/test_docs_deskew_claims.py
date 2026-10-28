"""What the README and the design note say about Deskew is what the code does."""

import re
from pathlib import Path

import pytest

from fastfoto_linux.documents import deskew_tables as t
from fastfoto_linux.documents.deskew import SkewStatus
from fastfoto_linux.documents.sidecar_versions import DESKEW_VERSION

ROOT = Path(__file__).resolve().parents[2]
DESIGN = (ROOT / "docs" / "design" / "documents.md").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")
ROADMAP = (ROOT / "docs" / "roadmaps" / "enhancements.md").read_text(encoding="utf-8")
SECTION = " ".join(DESIGN.split("### Deskew", 1)[-1].split("\n## ", 1)[0].split())
ACCURACY_CLAIM = re.compile(
    r"(?i)(improv|better|boost)\w*\s+(the\s+)?ocr|ocr accuracy|\d+ ?% accura"
)


def test_the_subsection_follows_despeckle_inside_paper_cleanup() -> None:
    headings = re.findall(r"(?m)^#{2,3} .*$", DESIGN)
    after = headings[headings.index("### Despeckle") + 1]
    assert after == "### Deskew"


@pytest.mark.parametrize(
    "phrase",
    [
        "off by default",
        "--deskew",
        "--no-deskew",
        "format version 6",
        "synthetic",
        "100 dpi",
        "same frame",
        "white",
        "deskew, then crop, then turn",
    ],
)
def test_the_design_note_says(phrase: str) -> None:
    assert phrase in SECTION


@pytest.mark.parametrize("status", [s.value for s in SkewStatus])
def test_every_abstain_reason_is_in_the_table(status: str) -> None:
    assert f"`{status}`" in SECTION


def test_the_constants_quoted_are_the_code_s() -> None:
    quoted = {
        t.WORK_DPI: "100 dpi",
        t.MIN_DPI: "under 100 dpi",
        t.MIN_INK_POINTS: "1500",
        t.MAX_INK_PCT: "35%",
        t.SEPARATION_TENTHS: "2.0",
        t.SEPARATION_PCT: "92%",
        t.CLIP_SLACK_PX: "1 work pixel",
        t.MAX_POINTS: "250,000",
        t.MAX_TENTHS: "10",
        t.OUTER_MAX_TENTHS: "45 degrees",
        t.CONTENT_DELTA: "40 levels",
        t.MIN_TENTHS: "0.3",
    }
    for value, words in quoted.items():
        assert words in SECTION, (value, words)
    assert (t.WORK_DPI, t.MIN_DPI, t.MIN_INK_POINTS, t.MAX_INK_PCT) == (100, 100, 1500, 35)
    assert (t.SEPARATION_TENTHS, t.SEPARATION_PCT, t.MAX_POINTS) == (20, 92, 250_000)
    assert (t.MAX_TENTHS, t.MIN_TENTHS, t.OUTER_STEP, t.OUTER_MAX_TENTHS) == (100, 3, 5, 450)
    assert (t.CLIP_SLACK_PX, t.CONTENT_DELTA) == (1, 40)
    assert DESKEW_VERSION == 6


def test_the_measured_separations_are_recorded() -> None:
    for phrase in ("0.51 to 0.53", "0.76 to 0.83", "0.99", "1.18 to 1.19"):
        assert phrase in SECTION


def test_the_readme_names_the_flag_and_the_default() -> None:
    text = " ".join(README.split())
    assert "--deskew" in text
    assert "off by default" in text.split("--deskew", 1)[1][:300]


def test_no_accuracy_claim() -> None:
    assert not ACCURACY_CLAIM.search(SECTION)
    assert not ACCURACY_CLAIM.search(" ".join(README.split()).split("--deskew", 1)[1][:900])


def test_the_roadmap_row_names_it() -> None:
    row = next(line for line in ROADMAP.splitlines() if line.startswith("| E06"))
    assert "document deskew (opt-in" in row.split("|")[2]
