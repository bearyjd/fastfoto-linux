"""The design note's threshold table is the table in code, and it claims no measured quality."""

import re
from pathlib import Path

from fastfoto_linux.evaluation.calib_thresholds import THRESHOLDS

ROOT = Path(__file__).resolve().parents[2]
DESIGN = ROOT / "docs" / "design" / "calibration-harness.md"
HEADER = (
    "| feature | constants | design note | harness | criterion | metric | op | value | automated |"
)


def table_rows() -> list[list[str]]:
    lines = DESIGN.read_text().splitlines()
    start = lines.index(HEADER) + 2  # skip the separator line
    rows = []
    for line in lines[start:]:
        if not line.startswith("|"):
            break
        rows.append([cell.strip().strip("`") for cell in line.strip("|").split("|")])
    return rows


def code_rows() -> list[list[str]]:
    rows = []
    for row in THRESHOLDS:
        head = [row.feature, row.family, row.design_doc, row.harness]
        if not row.criteria:
            rows.append([*head, "-", "-", "-", "-", "-"])
        for c in row.criteria:
            rows.append(
                [*head, c.key, c.metric, c.op, f"{c.value:g}", "yes" if c.automated else "no"]
            )
    return rows


def test_the_documented_table_equals_the_table_in_code() -> None:
    assert table_rows() == code_rows()


def test_the_note_states_the_limits_and_how_a_human_runs_it() -> None:
    text = DESIGN.read_text().lower()
    for phrase in (
        "synthetic self-tests only",
        "no quality has been measured",
        "tuned on synthetic data only",
        "fastfoto_corpus_dir",
        "--split tuning",
        "--expect-manifest-sha256",
        "--gate",
    ):
        assert phrase in text
    assert len(text.splitlines()) <= 300


def test_the_corpus_note_points_at_the_harness_note() -> None:
    assert "calibration-harness.md" in (ROOT / "docs" / "design" / "corpus.md").read_text()


def test_no_doc_claims_a_measured_accuracy() -> None:
    claims = re.compile(r"(?i)deskew (is|now) (accurate|reliable)|meets the (roadmap )?threshold")
    assert not claims.search(DESIGN.read_text())
