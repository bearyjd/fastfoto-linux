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
    "Or build the Flatpak (see the README), which has them built in. `ffscan` needs neither."
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


def destroy_now(item: Any) -> None:
    """Destroy a Qt object at once, if it still exists.

    ``deleteLater()`` is not enough when the event loop is done: it never runs, and PySide hands the
    object to C++ once it has been called, so the object outlives what it is bound to. Destroying
    the QML engine late left its window reading properties of a bridge that was already gone (about
    50 "Cannot read property ... of null" lines on quit).
    """
    import shiboken6  # noqa: PLC0415

    if shiboken6.isValid(item):
        shiboken6.delete(item)


# Bridges kept alive on purpose, see ``release_bridge``. The app calls that once, so this holds one
# at most, until the process exits; a later call (the tests make many) lets go of those whose job
# has ended since.
_LEFT_ALONE: list[Any] = []


def _let_go_of_finished() -> None:
    """Delete the bridges that were left alone and whose job has ended since."""
    finished = [bridge for bridge in _LEFT_ALONE if not bridge.job_alive]
    _LEFT_ALONE[:] = [bridge for bridge in _LEFT_ALONE if bridge.job_alive]
    for bridge in finished:
        destroy_now(bridge)


def release_bridge(bridge: Any) -> None:
    """Delete the bridge, unless the job's thread is still running (it is left alone then).

    ``shutdown`` waits a bounded time for the job, so a stubborn one can outlive it. Its thread
    holds the bridge as its sink: deleting the Qt object under it is not worth the risk when the
    process is about to exit anyway, so the bridge is kept (and never reported to again, as
    ``shutdown`` closed it).
    """
    _let_go_of_finished()
    if bridge.job_alive:
        logger.debug("the job is still running; the bridge is left to the end of the process")
        _LEFT_ALONE.append(bridge)
        return
    destroy_now(bridge)


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
    A second signal ends the wait at once (the scan is still told to stop).

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
    received = {"count": 0}

    def count_signal(*_: object) -> None:
        """Runs even while the GUI thread is blocked (the final wait): a second signal aborts.

        It also stays installed until the teardown is over, so it may run at any point of it: it
        only counts and assigns plain flags, no lock (see ``Bridge.give_up_waiting``), no logging.
        """
        received["count"] += 1
        if received["count"] > 1:
            bridge.give_up_waiting()

    previous = {number: signal.signal(number, count_signal) for number in STOP_SIGNALS}
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
        if state["stopping"]:  # a second signal: do not wait any longer, but stop the scan first
            bridge.abort()
            quit_once()
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
        destroy_now(notifier)  # and with it the handler that holds the bridge
        signal.set_wakeup_fd(old_fd)
        for number, handler in previous.items():
            signal.signal(number, handler)
        reader.close()
        writer.close()

    return undo


def _run(run_loop: Callable[[], int]) -> int:
    from fastfoto_linux.gui.qt.bridge import Bridge  # noqa: PLC0415
    from fastfoto_linux.gui.qt.messages import install_message_filter  # noqa: PLC0415

    bridge = Bridge()
    undo_filter = install_message_filter()  # before the QML engine loads KDE's style
    engine, warnings = create_engine(bridge)
    if not engine.rootObjects():
        undo_filter()
        print(f"fastfoto: the window could not be loaded: {'; '.join(warnings)}", file=sys.stderr)
        bridge.shutdown()  # closed before it is deleted: its threads may still be reporting
        destroy_now(engine)
        release_bridge(bridge)
        return 1
    from PySide6.QtWidgets import QApplication  # noqa: PLC0415

    app = QApplication.instance()
    undo_signals = handle_signals(bridge, app.quit)
    app.aboutToQuit.connect(bridge.shutdown)  # a quit from anywhere stops the job first
    bridge.checkScanner()
    try:
        return run_loop()
    finally:
        try:
            bridge.remember()
            bridge.shutdown()
            destroy_now(engine)  # the window first: it is bound to the bridge
            release_bridge(bridge)
        finally:
            # Last: until now a late signal (a second SIGTERM, say) is caught by our handler. With
            # the default one back it would kill the app in the middle of its teardown.
            undo_signals()
            undo_filter()
