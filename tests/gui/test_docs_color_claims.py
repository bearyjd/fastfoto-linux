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


def test_reset_adjustments_is_documented_as_covering_tone_and_white_balance():
    tone = " ".join((ROOT / "docs" / "design" / "photo-tone.md").read_text("utf-8").split())
    for text in (README, tone):
        assert "Reset adjustments" in text
        assert "tone and white balance" in text
    assert "sets every tone and white balance value" in README
    assert "overwrites" in README


def test_reset_adjustments_is_documented_as_also_clearing_detail():
    detail_labels = "Noise reduction, Colour noise and Sharpen"
    for name in ("photo-tone.md", "photo-white-balance.md", "photo-detail.md"):
        text = " ".join((ROOT / "docs" / "design" / name).read_text("utf-8").split())
        assert "Reset adjustments" in text and detail_labels in text, name
    assert "Reset adjustments" in README and detail_labels in README
    assert "presets leave" in README.lower() and "one Undo step" in README


def test_detail_sliders_are_documented_as_opt_in_and_slow_on_large_scans():
    design = " ".join((ROOT / "docs" / "design" / "photo-detail.md").read_text("utf-8").split())
    for text in (README, design):
        assert "off by default" in text and "slow" in text
    qml = (ROOT / "src" / "fastfoto_linux" / "gui" / "qml" / "PhotoDetailControls.qml").read_text(
        encoding="utf-8"
    )
    assert "Optional and off by default" in qml
