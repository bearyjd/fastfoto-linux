"""What ships: the entry point, the QML, the desktop file and icon; and what must not."""

import re
import shutil
import subprocess
import tomllib
import xml.etree.ElementTree as ET
from importlib.resources import files
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP_ID = "io.github.bearyjd.FastFotoLinux"
DESKTOP = ROOT / "packaging" / f"{APP_ID}.desktop"
ICON = ROOT / "packaging" / f"{APP_ID}.svg"
QML_FILES = (
    "Main.qml",
    "ScanPage.qml",
    "ScannerSettingsPage.qml",
    "FormPanel.qml",
    "ResultsView.qml",
    "PhotoCell.qml",
    "PhotoEditCanvas.qml",
    "PhotoEditPage.qml",
    "PhotoGeometryControls.qml",
    "PhotoToneControls.qml",
    "ModeSwitch.qml",
    "DocumentFormPanel.qml",
    "OcrLanguagePicker.qml",
    "DocumentsView.qml",
    "ReviewPage.qml",
    "ReviewCell.qml",
    "PreviewDialog.qml",
)
QML_DIR = ROOT / "src" / "fastfoto_linux" / "gui" / "qml"
CI = ROOT / ".github" / "workflows" / "ci.yml"
QML_CONTROL = re.compile(r"QQC2\.(?:Button|ToolButton|TextField|TextArea|ComboBox|CheckBox|Switch)")


def pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text())


def test_pyside6_is_not_a_pip_dependency_anywhere() -> None:
    """The PyPI wheel bundles its own Qt and cannot load the system Kirigami plugin."""
    config = pyproject()
    requirements = list(config["project"]["dependencies"])
    for extra in config["project"].get("optional-dependencies", {}).values():
        requirements += extra
    for group in config.get("dependency-groups", {}).values():
        requirements += [item for item in group if isinstance(item, str)]
    assert requirements
    assert not [r for r in requirements if re.match(r"(?i)(pyside|shiboken)", r)]
    assert "pyside" not in (ROOT / "uv.lock").read_text().lower()


def test_fastfoto_is_a_gui_script() -> None:
    assert pyproject()["project"]["gui-scripts"] == {"fastfoto": "fastfoto_linux.gui.qt.app:main"}
    assert pyproject()["project"]["scripts"]["ffscan"] == "fastfoto_linux.cli:main"


@pytest.mark.parametrize("name", QML_FILES)
def test_the_qml_is_package_data(name: str) -> None:
    qml = files("fastfoto_linux.gui") / "qml" / name
    assert qml.is_file()
    assert qml.read_text().startswith(("import ", "pragma "))


def test_the_main_window_is_a_kirigami_application_window() -> None:
    main = (files("fastfoto_linux.gui") / "qml" / "Main.qml").read_text()
    assert "import org.kde.kirigami as Kirigami" in main
    assert "Kirigami.ApplicationWindow" in main


def test_every_input_control_has_an_accessible_name() -> None:
    """Static check of the QML text: a control block without ``Accessible.name`` is a bug."""
    problems: list[str] = []
    for qml in (files("fastfoto_linux.gui") / "qml").iterdir():
        if not qml.name.endswith(".qml"):
            continue
        text = qml.read_text()
        for match in QML_CONTROL.finditer(text):
            if "Accessible.name" not in _block(text, match.end()):
                line = text.count("\n", 0, match.start()) + 1
                problems.append(f"{qml.name}:{line} {match.group(0)}")
    assert not problems, problems


def _block(text: str, start: int) -> str:
    """The text of the ``{ ... }`` block that begins at or after ``start``."""
    opening = text.index("{", start)
    depth = 0
    for position in range(opening, len(text)):
        depth += {"{": 1, "}": -1}.get(text[position], 0)
        if depth == 0:
            return text[opening : position + 1]
    raise AssertionError("unbalanced braces in QML")


@pytest.mark.skipif(shutil.which("desktop-file-validate") is None, reason="desktop-file-utils")
def test_the_desktop_file_is_valid() -> None:
    done = subprocess.run(
        ["desktop-file-validate", str(DESKTOP)], capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stdout + done.stderr


def test_the_desktop_file_launches_the_app_with_its_icon() -> None:
    entries = dict(line.split("=", 1) for line in DESKTOP.read_text().splitlines() if "=" in line)
    assert entries["Type"] == "Application"
    assert entries["Exec"] == "fastfoto"
    assert entries["TryExec"] == "fastfoto"
    assert entries["Icon"] == APP_ID
    assert "Graphics" in entries["Categories"]
    assert entries["Name"] == "FastFoto Linux"


def test_the_icon_is_a_scalable_svg() -> None:
    root = ET.parse(ICON).getroot()
    assert root.tag == "{http://www.w3.org/2000/svg}svg"
    assert root.get("viewBox")


# -- Review round 1 (items 9, 10 and 13) ---------------------------------------------------------


def test_the_list_of_qml_files_here_is_every_qml_file_there_is() -> None:
    assert sorted(path.name for path in QML_DIR.glob("*.qml")) == sorted(QML_FILES)


def test_the_ci_checks_every_qml_file_is_in_the_wheel_not_a_list_that_can_go_stale() -> None:
    workflow = CI.read_text()
    assert "gui/qml/*.qml" in workflow
    assert "for name in Main ScanPage" not in workflow


def test_the_fedora_image_is_pinned_by_digest_with_its_tag_in_a_comment() -> None:
    workflow = CI.read_text()
    assert re.search(r"container: fedora:44@sha256:[0-9a-f]{64}\b", workflow)
    assert re.search(r"#.*fedora:44", workflow)


def labelled_controls() -> list[tuple[str, str, str | None, str | None]]:
    """(file, objectName, Accessible.name, visible label) of every control that has a name."""
    found = []
    for qml in sorted(QML_DIR.glob("*.qml")):
        text = qml.read_text()
        for match in QML_CONTROL.finditer(text):
            block = _block(text, match.end())
            name = re.search(r'Accessible\.name: qsTr\("([^"]*)"\)', block)
            label = re.search(r'(?:\btext|Kirigami\.FormData\.label): qsTr\("([^"]*)"\)', block)
            ident = re.search(r'objectName: "([^"]+)"', block)
            found.append(
                (
                    qml.name,
                    ident.group(1) if ident else "?",
                    name.group(1) if name else None,
                    label.group(1).removesuffix(":") if label else None,
                )
            )
    return found


def test_a_control_is_named_for_assistive_technology_as_it_is_labelled_on_screen() -> None:
    """The name must contain the visible label (WCAG 2.5.3): here, be equal to it."""
    controls = labelled_controls()
    assert len(controls) >= 14
    wrong = [c for c in controls if c[3] is not None and c[2] != c[3]]
    assert not wrong, wrong


def test_the_folder_field_is_named_for_the_label_beside_it() -> None:
    names = {ident: name for _, ident, name, _ in labelled_controls()}
    assert names["folderField"] == "Save photos in"


def test_the_scanner_chip_is_named_by_what_it_says() -> None:
    page = (QML_DIR / "ScanPage.qml").read_text()
    chip = _block(page, page.index("Kirigami.Chip"))
    assert "Scanner status:" not in chip


def test_every_label_shows_its_text_as_plain_text() -> None:
    """Album, folder and error texts come from the user or the disk: never markup."""
    problems = []
    for qml in sorted(QML_DIR.glob("*.qml")):
        text = qml.read_text()
        for match in re.finditer(r"QQC2\.Label\b", text):
            if "textFormat: Text.PlainText" not in _block(text, match.end()):
                problems.append(f"{qml.name}:{text.count(chr(10), 0, match.start()) + 1}")
    assert not problems, problems


def test_the_inline_messages_show_escaped_text_because_they_have_no_text_format() -> None:
    """Kirigami's InlineMessage renders AutoText: the bridge hands it text that is escaped."""
    problems = []
    for qml in sorted(QML_DIR.glob("*.qml")):
        text = qml.read_text()
        for match in re.finditer(r"Kirigami\.InlineMessage\b", text):
            block = _block(text, match.end())
            raw_text = re.search(r"^\s*text:.*bridge\.(banner|kept)Text", block, re.MULTILINE)
            if "Html" not in block or raw_text:
                problems.append(f"{qml.name}:{text.count(chr(10), 0, match.start()) + 1}")
    assert not problems, problems


def test_every_picture_of_a_photo_cell_is_scaled_to_fit_not_stretched() -> None:
    text = (QML_DIR / "PhotoCell.qml").read_text()
    images = [
        _block(text, match.end()) for match in re.finditer(r"^\s*Image\b", text, re.MULTILINE)
    ]
    assert len(images) == 2
    assert all("fillMode: Image.PreserveAspectFit" in block for block in images)


# -- the build backend is pinned by hash like everything else the installer fetches ------------

BUILD_IN = ROOT / "packaging" / "requirements-build.in"
BUILD_TXT = ROOT / "packaging" / "requirements-build.txt"


def pinned_blocks(path: Path) -> list[list[str]]:
    """The requirement entries of a pip requirements file, each with its continuation lines."""
    blocks: list[list[str]] = []
    for line in path.read_text().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        if line.startswith(" ") and blocks:
            blocks[-1].append(line.strip())
        else:
            blocks.append([line.strip()])
    return blocks


def test_every_build_requirement_is_pinned_and_has_hashes() -> None:
    blocks = pinned_blocks(BUILD_TXT)
    names = {block[0].split("==")[0].lower() for block in blocks}
    assert "hatchling" in names
    for block in blocks:
        assert "==" in block[0], block
        assert any("--hash=sha256:" in part for part in block), block


def test_the_build_requirements_start_from_the_backend_pyproject_asks_for() -> None:
    wanted = pyproject()["build-system"]["requires"]
    assert [line for line in BUILD_IN.read_text().splitlines() if line and line[0] != "#"] == wanted


def test_ci_installs_the_gui_job_from_the_hashed_files() -> None:
    text = CI.read_text()
    assert "uv pip install -e . --group dev" not in text
    assert "--require-hashes" in text
    assert "python3-gobject-base" in text  # the launcher's GLib round-trip test runs there
