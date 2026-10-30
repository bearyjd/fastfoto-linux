"""What the README and design note say about the colour presets is what the editor offers."""

from pathlib import Path

from fastfoto_linux.gui.photoeditpresets import PRESETS

ROOT = Path(__file__).resolve().parents[2]
QML = ROOT / "src" / "fastfoto_linux" / "gui" / "qml" / "PhotoWhiteBalanceControls.qml"
README = " ".join((ROOT / "README.md").read_text(encoding="utf-8").split())
DESIGN = " ".join(
    (ROOT / "docs" / "design" / "photo-white-balance.md").read_text(encoding="utf-8").split()
)


def test_the_readme_lists_the_preset_labels_in_order():
    positions = [README.index(f"`{item.label}`") for item in PRESETS]
    assert positions == sorted(positions)
    assert [item.label for item in PRESETS] == [
        "Warm",
        "Cool",
        "Faded print",
        "Black and white",
    ]


def test_the_docs_say_presets_are_one_undo_step_not_saved_and_reset_covers_balance():
    for text in (README, DESIGN):
        assert "one Undo step" in text or "one undo step" in text
    assert "not saved in the recipe" in README
    assert "not stored in the recipe" in DESIGN
    assert "Reset adjustments" in README and "Temperature and Tint" in README


def test_the_qml_offers_the_documented_presets_and_hint():
    text = QML.read_text(encoding="utf-8")
    for item in PRESETS:
        assert f'presetId: "{item.id}"' in text
    assert "lower is cooler (blue), higher is warmer (yellow)" in text
