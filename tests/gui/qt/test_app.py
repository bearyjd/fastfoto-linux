from pathlib import Path
from typing import Any

import pytest

from tests.gui.qt import require_qt

require_qt()

from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

from fastfoto_linux.gui import worker as worker_module
from fastfoto_linux.gui.prefs import PREFS_DIR, PREFS_FILE
from fastfoto_linux.gui.qt import app
from fastfoto_linux.gui.qt.app import create_engine
from fastfoto_linux.scanner import ScanTarget
from tests.cli.fakes import DEVICE
from tests.gui.qt.qt_helpers import settle


def test_the_kde_desktop_style_is_used_when_it_is_installed(qapp: Any) -> None:
    app.configure_style()
    assert QQuickStyle.name() in ("org.kde.desktop", "Fusion", "Basic")
    if QQuickStyle.name() != "org.kde.desktop":
        pytest.skip("qqc2-desktop-style is not installed")


def test_the_engine_loads_the_window_without_warnings(
    make_bridge: Any, kirigami: None, messages: list[str]
) -> None:
    engine, warnings = create_engine(make_bridge())
    try:
        assert len(engine.rootObjects()) == 1
        assert warnings == []
        assert messages == []
    finally:
        engine.rootObjects()[0].close()
        engine.deleteLater()
        settle()


def test_without_kirigami_it_says_what_to_install_and_exits_3(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], qapp: Any
) -> None:
    shown: list[str] = []
    monkeypatch.setattr(app, "kirigami_available", lambda paths: False)
    monkeypatch.setattr(app, "show_error_dialog", shown.append)
    assert app.main() == app.EXIT_MISSING_QT
    err = capsys.readouterr().err
    assert "kf6-kirigami" in err
    assert "python3-pyside6" in err
    assert "Flatpak" in err
    assert shown == [err.strip()]


def test_main_runs_the_event_loop_and_remembers_the_form(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kirigami: None, qapp: Any
) -> None:
    config = tmp_path / "config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    monkeypatch.setattr(worker_module, "default_discover", lambda: ScanTarget(device=DEVICE))
    loops: list[str] = []

    def run_loop() -> int:
        loops.append(QApplication.applicationName())
        settle()
        return 7

    assert app.main(run_loop=run_loop) == 7
    assert loops == ["fastfoto-linux"]
    assert QApplication.desktopFileName() == app.APP_ID
    assert (config / PREFS_DIR / PREFS_FILE).is_file()
    settle()
