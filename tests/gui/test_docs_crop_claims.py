"""What the README and the design note say about the crop controls is what the GUI has."""

import re
from pathlib import Path

from fastfoto_linux.gui.review import CROP_TEXT
from fastfoto_linux.gui.reviewnames import MAX_CROP_PREVIEWS
from fastfoto_linux.photo_edits.model import MIN_CROP_MM

ROOT = Path(__file__).resolve().parents[2]
QML = (ROOT / "src" / "fastfoto_linux" / "gui" / "qml" / "PreviewDialog.qml").read_text()
README = " ".join((ROOT / "README.md").read_text(encoding="utf-8").split())
DESIGN = " ".join((ROOT / "docs" / "design" / "documents.md").read_text(encoding="utf-8").split())


def test_the_readme_names_the_buttons_the_dialog_has() -> None:
    for label in ("Crop", "Reset crop"):
        assert f'text: qsTr("{label}")' in QML
    assert "**Reset crop**" in README


def test_the_minimum_the_docs_state_is_the_one_the_code_enforces() -> None:
    assert MIN_CROP_MM == 5
    assert f"at least {int(MIN_CROP_MM)} mm" in README
    assert f"at least {int(MIN_CROP_MM)} mm" in DESIGN
    assert "at least 5 mm on each side" in QML


def test_the_design_note_states_the_preview_bound_and_the_row_text() -> None:
    assert f"at most {MAX_CROP_PREVIEWS} per page" in DESIGN
    assert CROP_TEXT == "Cropped by hand"
    assert re.search(r"never from a user or file value", DESIGN)
