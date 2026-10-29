"""What the README, the design note and the roadmap say about the Straighten controls."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QML_DIR = ROOT / "src" / "fastfoto_linux" / "gui" / "qml"


def words(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


README = words(ROOT / "README.md")
DESIGN = words(ROOT / "docs" / "design" / "documents.md")
ROADMAP = (ROOT / "docs" / "roadmaps" / "enhancements.md").read_text(encoding="utf-8")
FORM_LABEL = "Straighten tilted pages"


def desktop_section() -> str:
    return README.split("## Desktop app (preview)")[1].split("### Flatpak")[0]


def test_the_readme_names_the_desktop_controls_the_qml_offers() -> None:
    form = words(QML_DIR / "DocumentFormPanel.qml")
    review = words(QML_DIR / "ReviewPage.qml")
    assert f'qsTr("{FORM_LABEL}")' in form
    assert 'qsTr("Straighten page")' in review and 'qsTr("Undo straighten")' in review
    desktop = desktop_section()
    assert f"**{FORM_LABEL}**" in desktop
    assert "**Straighten page**" in desktop and "**Undo straighten**" in desktop


def test_the_readme_says_new_scans_only_and_that_straighten_removes_the_crop() -> None:
    after = desktop_section().split(FORM_LABEL)[1]
    assert "new scan" in after and "never measured" in after
    assert "crop" in after


def test_the_design_note_describes_the_desktop_controls_and_the_preview_names() -> None:
    section = DESIGN.split("### Deskew")[1].split("\n## ")[0]
    assert "desktop" in section and "-straight-" in section


def test_the_roadmap_no_longer_says_desktop_deskew_is_unimplemented() -> None:
    row = " ".join(next(line for line in ROADMAP.splitlines() if "deskew" in line.lower()).split())
    assert "deskew in the desktop app" not in row
    assert "the API and the desktop form and review screen" in row
