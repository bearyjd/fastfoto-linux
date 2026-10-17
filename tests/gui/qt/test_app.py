from pathlib import Path
from typing import Any

import pytest

from tests.gui.qt import require_qt, unavailable

require_qt()

from PySide6.QtCore import QLoggingCategory, qCWarning
from PySide6.QtQml import QQmlApplicationEngine
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
        unavailable("qqc2-desktop-style is not installed")


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


def test_the_known_kde_lines_are_hidden_while_the_app_runs_and_shown_again_after(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kirigami: None, qapp: Any, messages: list[str]
) -> None:
    from PySide6.QtCore import QLoggingCategory, qCWarning

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(worker_module, "default_discover", lambda: ScanTarget(device=DEVICE))
    category = QLoggingCategory("kf.kio.widgets.kdirmodel")
    temp = 'No node found for item that was just removed: QUrl("file:///photos/.ffscan-raw-ab12cd")'
    other = 'No node found for item that was just removed: QUrl("file:///photos/Holiday")'

    def run_loop() -> int:
        qCWarning(category, temp)
        qCWarning(category, other)
        return 0

    assert app.main(run_loop=run_loop) == 0
    assert messages == [other]
    qCWarning(category, temp)  # the app has put the previous handler back
    assert messages == [other, temp]
    settle()


KDIRMODEL = "kf.kio.widgets.kdirmodel"
TEMP_REMOVED = (
    'No node found for item that was just removed: QUrl("file:///photos/.ffscan-raw-ab12cd")'
)


def warn_temp_folder_removed() -> None:
    qCWarning(QLoggingCategory(KDIRMODEL), TEMP_REMOVED)


def test_the_filter_is_on_while_the_engine_loads_and_off_after_a_failed_load(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    kirigami: None,
    messages: list[str],
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    def engine_that_does_not_load(bridge: Any) -> tuple[Any, list[str]]:
        warn_temp_folder_removed()  # KDE's style prints its lines while the window loads
        return QQmlApplicationEngine(), ["boom"]

    monkeypatch.setattr(app, "create_engine", engine_that_does_not_load)
    assert app.main(run_loop=lambda: 0) == 1
    assert messages == []  # hidden while the engine loaded
    warn_temp_folder_removed()
    assert messages == [TEMP_REMOVED]  # the previous handler is back
    settle()


def test_the_filter_is_taken_off_when_creating_the_engine_raises(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    kirigami: None,
    messages: list[str],
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    def engine_that_raises(bridge: Any) -> tuple[Any, list[str]]:
        raise RuntimeError("no engine today")

    monkeypatch.setattr(app, "create_engine", engine_that_raises)
    with pytest.raises(RuntimeError, match="no engine today"):
        app.main(run_loop=lambda: 0)
    warn_temp_folder_removed()
    assert messages == [TEMP_REMOVED]  # the previous handler is back
    settle()


# -- Quitting while a scan runs: logout, `kill`, Ctrl+C in a terminal (item 7) ------------------


def test_closing_the_app_cancels_and_joins_a_running_scan_first(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kirigami: None, qapp: Any
) -> None:
    from fastfoto_linux.gui.qt import bridge as bridge_module
    from tests.gui.helpers import ScriptedSession
    from tests.gui.qt.qt_helpers import wait_until

    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(worker_module, "default_discover", lambda: ScanTarget(device=DEVICE))
    session = ScriptedSession(out, hold=True)
    monkeypatch.setattr(worker_module, "run_session", session)
    seen: list[Any] = []

    class Spy(bridge_module.Bridge):
        def __init__(self) -> None:
            super().__init__(form=bridge_module.ScanForm(output_folder=str(out)))
            seen.append(self)

    monkeypatch.setattr(bridge_module, "Bridge", Spy)
    after: list[bool] = []

    def run_loop() -> int:
        bridge = seen[0]
        wait_until(lambda: bridge.canScan, "ready")
        bridge.startScan()
        wait_until(lambda: bridge.canCancel, "the scan to hold")
        QApplication.instance().aboutToQuit.emit()  # what Qt does as the loop ends
        after.append(bridge._worker.busy)
        return 0

    assert app.main(run_loop=run_loop) == 0
    assert after == [False]
    settle()


def test_the_signal_handlers_are_undone_when_the_app_is_done(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kirigami: None, qapp: Any
) -> None:
    import signal

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(worker_module, "default_discover", lambda: ScanTarget(device=DEVICE))
    names = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)
    before = [signal.getsignal(name) for name in names]
    inside: list[list[Any]] = []

    def run_loop() -> int:
        inside.append([signal.getsignal(name) for name in names])
        return 0

    assert app.main(run_loop=run_loop) == 0
    assert inside[0] != before  # the app took the signals over while it ran
    assert [signal.getsignal(name) for name in names] == before
    settle()
