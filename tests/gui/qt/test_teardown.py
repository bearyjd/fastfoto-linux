"""Quitting: the QML window goes first, then the bridge it is bound to (review round 1, item 1).

``engine.deleteLater()`` after the event loop has returned never runs, and PySide gives an object
to C++ once ``deleteLater`` is called on it. The bridge, owned by Python, then died when ``_run``
returned while the QML tree lived on and read properties of a bridge that was gone: about 50
"Cannot read property ... of null" lines on quit under Python 3.13 (silent under 3.14), so the
tests below look at the order of destruction, which does not depend on the Python version.
"""

from pathlib import Path
from typing import Any

import pytest

from tests.gui.qt import require_qt

require_qt()

import PySide6.QtCore as qtcore
import shiboken6

from fastfoto_linux.gui import worker as worker_module
from fastfoto_linux.gui.qt import app
from fastfoto_linux.gui.qt.app import handle_signals
from fastfoto_linux.scanner import ScanTarget
from tests.cli.fakes import DEVICE
from tests.gui.qt.qt_helpers import settle

pytestmark = pytest.mark.usefixtures("kirigami")


@pytest.fixture
def quiet_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``app.main`` with a fake scanner and its settings in a temporary folder."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(worker_module, "default_discover", lambda: ScanTarget(device=DEVICE))


@pytest.fixture
def destroyed(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The order in which the window's engine and the bridge are destroyed (nothing keeps them)."""
    order: list[str] = []
    real_create = app.create_engine

    def create(bridge: Any) -> tuple[Any, list[str]]:
        engine, warnings = real_create(bridge)
        engine.destroyed.connect(lambda *_: order.append("engine"))
        bridge.destroyed.connect(lambda *_: order.append("bridge"))
        return engine, warnings

    monkeypatch.setattr(app, "create_engine", create)
    return order


def test_the_engine_is_destroyed_before_the_bridge_and_before_main_returns(
    quiet_app: None, destroyed: list[str], qapp: Any
) -> None:
    assert app.main(run_loop=lambda: 0) == 0
    # No event loop runs after main(): whatever is left for one is never destroyed.
    assert destroyed[:1] == ["engine"], destroyed


def test_the_bridge_goes_with_the_window_when_the_app_is_done(
    quiet_app: None, destroyed: list[str], qapp: Any
) -> None:
    assert app.main(run_loop=lambda: 0) == 0
    assert destroyed == ["engine", "bridge"]


def test_the_signal_handlers_come_back_last_after_the_window_and_the_bridge_are_gone(
    quiet_app: None, destroyed: list[str], monkeypatch: pytest.MonkeyPatch, qapp: Any
) -> None:
    """A signal that lands during the teardown must still reach our handler, not the default."""
    real_handle = app.handle_signals

    def handle(*arguments: Any, **options: Any) -> Any:
        undo = real_handle(*arguments, **options)

        def undo_and_note() -> None:
            destroyed.append("handlers back")
            undo()

        return undo_and_note

    monkeypatch.setattr(app, "handle_signals", handle)
    assert app.main(run_loop=lambda: 0) == 0
    assert destroyed == ["engine", "bridge", "handlers back"]


def test_a_window_that_could_not_be_loaded_is_destroyed_too(
    quiet_app: None,
    destroyed: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    qapp: Any,
) -> None:
    monkeypatch.setattr(app, "qml_main", lambda: Path("/nonexistent/Main.qml"))
    assert app.main(run_loop=lambda: 0) == 1
    assert "could not be loaded" in capsys.readouterr().err
    assert destroyed[:1] == ["engine"], destroyed


def test_quitting_after_the_window_loaded_logs_no_qml_warnings(
    quiet_app: None, messages: list[str], qapp: Any
) -> None:
    def run_loop() -> int:
        settle()
        return 0

    assert app.main(run_loop=run_loop) == 0
    settle()  # whatever is still queued for the event loop runs now
    assert messages == []


def test_undoing_the_signal_handlers_destroys_the_socket_notifier(
    make_bridge: Any, monkeypatch: pytest.MonkeyPatch, qapp: Any
) -> None:
    made: list[Any] = []

    class Watched(qtcore.QSocketNotifier):
        def __init__(self, *arguments: Any) -> None:
            super().__init__(*arguments)
            made.append(self)

    monkeypatch.setattr(qtcore, "QSocketNotifier", Watched)
    undo = handle_signals(make_bridge(), lambda: None)
    undo()
    [notifier] = made
    assert not shiboken6.isValid(notifier)  # not "later": nothing runs the event loop again
