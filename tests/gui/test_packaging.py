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
QML_FILES = ("Main.qml", "ScanPage.qml", "FormPanel.qml", "ResultsView.qml")
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
    assert entries["Icon"] == APP_ID
    assert "Graphics" in entries["Categories"]
    assert entries["Name"] == "FastFoto Linux"


def test_the_icon_is_a_scalable_svg() -> None:
    root = ET.parse(ICON).getroot()
    assert root.tag == "{http://www.w3.org/2000/svg}svg"
    assert root.get("viewBox")
