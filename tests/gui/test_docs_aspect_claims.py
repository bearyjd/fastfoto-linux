"""What the README, the design note and the roadmap say about crop shapes is what the app does."""

import re
from pathlib import Path

from fastfoto_linux.gui.photoeditaspect import PRESETS
from fastfoto_linux.photo_edits.recipe import GEOMETRY_KEYS, STRAIGHTEN_KEYS

ROOT = Path(__file__).resolve().parents[2]
QML_DIR = ROOT / "src" / "fastfoto_linux" / "gui" / "qml"
README = (ROOT / "README.md").read_text(encoding="utf-8")
DESIGN = (ROOT / "docs" / "design" / "photo-geometry.md").read_text(encoding="utf-8")
ROADMAP = (ROOT / "docs" / "roadmaps" / "enhancements.md").read_text(encoding="utf-8")


def raw_paragraph() -> str:
    match = re.search(r"^\*\*Crop shape\*\*.*?(?=\n\n)", README, re.M | re.S)
    assert match, "the README has no Crop shape paragraph"
    return match.group(0)


def crop_shape_paragraph() -> str:
    return " ".join(raw_paragraph().split())


def test_the_readme_lists_the_labels_the_qml_offers_in_the_order_of_the_presets():
    controls = (QML_DIR / "PhotoGeometryControls.qml").read_text(encoding="utf-8")
    paragraph = crop_shape_paragraph()
    labels = [preset.label for preset in PRESETS]
    assert labels == ["Free", "Original", "1:1", "4:3", "3:2", "16:9", "5:7"]
    for label in labels:
        assert f"`{label}`" in paragraph
        assert f'qsTr("{label}")' in controls
    positions = [paragraph.index(f"`{label}`") for label in labels]
    assert positions == sorted(positions)


def test_the_readme_says_what_choosing_dragging_and_typing_do():
    paragraph = crop_shape_paragraph()
    assert "saved picture after" in paragraph
    assert "largest centred box" in paragraph and "5 mm" in paragraph
    assert "**Swap orientation**" in paragraph
    assert "Dragging" in paragraph and "keeps the shape" in paragraph
    assert "edge box" in paragraph and "returns to `Free`" in paragraph
    assert len(raw_paragraph().splitlines()) <= 6


def test_the_readme_says_the_shape_is_not_stored_and_a_reopened_edit_starts_free():
    paragraph = crop_shape_paragraph()
    assert "not saved in the recipe" in paragraph
    assert "reopened edit starts at `Free`" in paragraph


def test_the_design_note_has_the_crop_shapes_section_and_no_longer_denies_presets():
    assert "There are no aspect presets" not in DESIGN
    section = re.search(r"^## Crop shapes \(editor only\)\n(.*?)(?=^## |\Z)", DESIGN, re.M | re.S)
    assert section, "the design note has no Crop shapes section"
    body = section.group(1)
    assert len(body.strip().splitlines()) <= 15
    assert "half up" in body and "not stored in the recipe" in body
    assert "straightened frame" in body and "quarter turns" in body


def test_the_roadmap_row_lists_aspect_presets_as_implemented_not_missing() -> None:
    row = next(line for line in ROADMAP.splitlines() if line.startswith("| E05 — basic photo"))
    cells = [cell.strip() for cell in row.strip("|").split("|")]
    _name, done, missing = cells[:3]
    assert "aspect presets" in done
    assert "aspect" not in missing


def test_nothing_new_is_stored_in_the_recipe():
    assert {"quarter_turns", "crop"} == GEOMETRY_KEYS
    assert {"quarter_turns", "crop", "straighten_tenths"} == STRAIGHTEN_KEYS
