"""``fastfoto``: start the desktop app."""

import logging
import os
import signal
import socket
import sys
from collections.abc import Callable
from importlib.resources import files
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

EXIT_MISSING_QT = 3
STOP_SIGNALS = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)  # kill, Ctrl+C, logout
SIGNAL_SETTLE_SECONDS = 10.0  # how long a signalled app waits for the scan to stop
SIGNAL_READ_BYTES = 4096
APP_ID = "io.github.bearyjd.FastFotoLinux"
APP_NAME = "fastfoto-linux"
DISPLAY_NAME = "FastFoto Linux"
STYLE = "org.kde.desktop"
STYLE_ENV_VAR = "QT_QUICK_CONTROLS_STYLE"
MISSING_QT_MESSAGE = (
    "fastfoto: the desktop app needs the distribution's PySide6 and Kirigami (the PyPI PySide6 "
    "wheel bundles its own Qt and cannot load Kirigami).\n"
    "On Fedora: sudo dnf install python3-pyside6 kf6-kirigami\n"
    "Or use the Flatpak, which has them built in (coming soon). `ffscan` needs neither."
)


def kirigami_available(import_paths: list[str]) -> bool:
    """True when one of the QML import folders has the Kirigami module."""
    return _module_installed(import_paths, "org", "kde", "kirigami")


def _module_installed(import_paths: list[str], *parts: str) -> bool:
    return any(Path(folder, *parts).is_dir() for folder in import_paths if "://" not in folder)


def _import_paths() -> list[str]:
    from PySide6.QtQml import QQmlEngine  # noqa: PLC0415 - Qt is imported only when it runs

    return QQmlEngine().importPathList()


def configure_style() -> None:
    """Use the KDE desktop style for the controls when it is installed.

    A style chosen by the user (``QT_QUICK_CONTROLS_STYLE``) is left alone, and setting it twice
    is harmless: Qt does not accept a style once the controls have been loaded.
    """
    from PySide6.QtQuickControls2 import QQuickStyle  # noqa: PLC0415

    if os.environ.get(STYLE_ENV_VAR) or QQuickStyle.name() == STYLE:
        return
    if _module_installed(_import_paths(), "org", "kde", "desktop"):
        QQuickStyle.setStyle(STYLE)


def qml_main() -> Path:
    return Path(str(files("fastfoto_linux.gui") / "qml" / "Main.qml"))


def create_engine(bridge: Any) -> tuple[Any, list[str]]:
    """The QML engine with the window loaded, and the list its warnings are collected in."""
    from PySide6.QtCore import QUrl  # noqa: PLC0415
    from PySide6.QtQml import QQmlApplicationEngine  # noqa: PLC0415

    engine = QQmlApplicationEngine()
    warnings: list[str] = []
    engine.warnings.connect(lambda items: warnings.extend(item.toString() for item in items))
    engine.rootContext().setContextProperty("bridge", bridge)
    engine.load(QUrl.fromLocalFile(str(qml_main())))
    return engine, warnings


def show_error_dialog(text: str) -> None:
    """Tell the user in a dialog too: a launcher has no terminal to print to."""
    from PySide6.QtWidgets import QMessageBox  # noqa: PLC0415

    QMessageBox(QMessageBox.Icon.Critical, DISPLAY_NAME, text).exec()


def _fail(message: str, *, dialog: bool) -> int:
    print(message, file=sys.stderr)
    if dialog:
        try:
            show_error_dialog(message)
        except Exception:
            logger.exception("could not show the error dialog")
    return EXIT_MISSING_QT


def main(run_loop: Callable[[], int] | None = None) -> int:
    """Run the app; returns its exit code (3 when PySide6 or Kirigami is missing)."""
    try:
        import PySide6  # noqa: F401, PLC0415
    except ImportError:
        return _fail(MISSING_QT_MESSAGE, dialog=False)
    from PySide6.QtGui import QGuiApplication  # noqa: PLC0415
    from PySide6.QtWidgets import QApplication  # noqa: PLC0415

    app = QApplication.instance() or QApplication(sys.argv)
    QGuiApplication.setApplicationName(APP_NAME)
    QGuiApplication.setApplicationDisplayName(DISPLAY_NAME)
    QGuiApplication.setDesktopFileName(APP_ID)  # the window gets its icon under Wayland
    if not kirigami_available(_import_paths()):
        return _fail(MISSING_QT_MESSAGE, dialog=True)
    configure_style()
    return _run(run_loop or app.exec)


def handle_signals(
    bridge: Any, quit_: Callable[[], None], *, settle_timeout: float = SIGNAL_SETTLE_SECONDS
) -> Callable[[], None]:
    """Stop cleanly on SIGTERM, SIGINT and SIGHUP: cancel a running scan, wait, then ``quit_``.

    Without this a logout or ``kill`` ends the app in the middle of a scan, leaving scanimage
    running and the raw pages unsettled. Python only runs a signal handler when Python code is
    running, which a Qt event loop waiting for input never is, so the signal also writes a byte
    to a socket that a ``QSocketNotifier`` watches. The wait for the scan to settle is bounded
    by ``settle_timeout``. Returns the function that puts the previous handlers back.
    """
    from PySide6.QtCore import QSocketNotifier, QTimer  # noqa: PLC0415

    reader, writer = socket.socketpair()
    reader.setblocking(False)
    writer.setblocking(False)
    previous = {number: signal.signal(number, lambda *_: None) for number in STOP_SIGNALS}
    old_fd = signal.set_wakeup_fd(writer.fileno(), warn_on_full_buffer=False)
    notifier = QSocketNotifier(reader.fileno(), QSocketNotifier.Type.Read)
    state = {"stopping": False, "quit": False}

    def quit_once() -> None:
        if not state["quit"]:
            state["quit"] = True
            quit_()

    def on_signal() -> None:
        try:
            reader.recv(SIGNAL_READ_BYTES)
        except BlockingIOError:
            return
        if state["stopping"]:
            return
        state["stopping"] = True
        if bridge.requestClose():  # nothing is running
            quit_once()
            return
        bridge.closeReady.connect(quit_once)  # the cancel has settled
        QTimer.singleShot(round(settle_timeout * 1000), quit_once)

    notifier.activated.connect(on_signal)

    def undo() -> None:
        notifier.setEnabled(False)
        notifier.deleteLater()
        signal.set_wakeup_fd(old_fd)
        for number, handler in previous.items():
            signal.signal(number, handler)
        reader.close()
        writer.close()

    return undo


def _run(run_loop: Callable[[], int]) -> int:
    from fastfoto_linux.gui.qt.bridge import Bridge  # noqa: PLC0415

    bridge = Bridge()
    engine, warnings = create_engine(bridge)
    if not engine.rootObjects():
        print(f"fastfoto: the window could not be loaded: {'; '.join(warnings)}", file=sys.stderr)
        return 1
    from PySide6.QtWidgets import QApplication  # noqa: PLC0415

    app = QApplication.instance()
    undo_signals = handle_signals(bridge, app.quit)
    app.aboutToQuit.connect(bridge.shutdown)  # a quit from anywhere stops the job first
    bridge.checkScanner()
    try:
        return run_loop()
    finally:
        undo_signals()
        bridge.remember()
        bridge.shutdown()
        engine.deleteLater()
