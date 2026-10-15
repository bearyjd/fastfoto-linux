"""``fastfoto`` without the Qt stack says how to get it instead of showing a traceback."""

import sys
from pathlib import Path

import pytest

from fastfoto_linux.gui.qt import app


def test_kirigami_is_found_in_an_import_folder(tmp_path: Path) -> None:
    (tmp_path / "org" / "kde" / "kirigami").mkdir(parents=True)
    assert app.kirigami_available(["qrc:/qt/qml", str(tmp_path)])


def test_kirigami_is_missing_from_folders_without_it(tmp_path: Path) -> None:
    (tmp_path / "org" / "kde").mkdir(parents=True)
    assert not app.kirigami_available([str(tmp_path), "qrc:/qt-project.org/imports"])
    assert not app.kirigami_available([])


def test_without_pyside6_it_explains_and_exits_3(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setitem(sys.modules, "PySide6", None)
    assert app.main() == app.EXIT_MISSING_QT == 3
    message = capsys.readouterr().err
    assert "python3-pyside6" in message
    assert "kf6-kirigami" in message
    assert "Flatpak" in message
