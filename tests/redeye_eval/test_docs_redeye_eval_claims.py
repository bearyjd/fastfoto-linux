"""The docs describe the harness without claiming any measured accuracy."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DESIGN = ROOT / "docs" / "design" / "redeye-evaluation.md"
ROADMAP = ROOT / "docs" / "roadmaps" / "enhancements.md"
README = ROOT / "README.md"
CLAIMS = re.compile(
    r"(?i)no false positives|zero false positives|100% (accurate|precision)"
    r"|red-eye (is|now) (accurate|reliable)"
)


def test_the_design_note_states_the_limits_and_the_method() -> None:
    text = DESIGN.read_text()
    for phrase in ("no accuracy has been measured", "inter-ocular", "Wilson", "95% upper bound"):
        assert phrase in text
    assert len(text.splitlines()) <= 120


def test_the_roadmap_rows_still_say_there_is_no_held_out_data() -> None:
    text = ROADMAP.read_text()
    assert "red-eye evaluation harness" in text
    assert "held-out" in text and "experimental defaults" in text
    assert "no corpus has been run" in text


def test_no_doc_claims_accuracy() -> None:
    for path in (DESIGN, README):
        assert not CLAIMS.search(path.read_text()), path.name
