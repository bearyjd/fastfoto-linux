"""What the README, the design note and the roadmap say about the Remove specks controls."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QML_DIR = ROOT / "src" / "fastfoto_linux" / "gui" / "qml"


def words(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


README = words(ROOT / "README.md")
DESIGN = words(ROOT / "docs" / "design" / "documents.md")
ROADMAP = (ROOT / "docs" / "roadmaps" / "enhancements.md").read_text(encoding="utf-8")
FORM_LABEL = "Remove specks (black and white pages)"


def test_the_readme_names_the_desktop_controls_the_qml_offers() -> None:
    form = words(QML_DIR / "DocumentFormPanel.qml")
    review = words(QML_DIR / "ReviewPage.qml")
    assert f'qsTr("{FORM_LABEL}")' in form
    assert 'qsTr("Remove specks for the document")' in review
    desktop = README.split("## Desktop app (preview)")[1].split("### Flatpak")[0]
    assert f"**{FORM_LABEL}**" in desktop
    assert "review screen" in desktop and "Remove specks" in desktop.split(FORM_LABEL)[-1]


def test_the_readme_says_the_preview_switch_covers_specks_and_off_by_default() -> None:
    desktop = README.split("## Desktop app (preview)")[1].split("### Flatpak")[0]
    assert "off by default" in desktop.split(FORM_LABEL)[1][:600]
    assert "Paper cleanup** switch" in desktop.split(FORM_LABEL)[1]


def test_the_design_note_describes_the_desktop_controls_and_the_preview_names() -> None:
    section = DESIGN.split("### Despeckle")[1].split("## Manual crop")[0]
    assert "desktop" in section and "review page" in section
    assert "-s" in section and "bw-off" in section


def test_the_roadmap_no_longer_says_the_review_control_is_to_come() -> None:
    row = " ".join(next(line for line in ROADMAP.splitlines() if line.startswith("| E06")).split())
    assert "review-screen control is still to come" not in row
    assert "despeckle (black and white only, opt-in)" in row
