"""Qt and QML test fixtures: one QApplication, offscreen, software rendering.

The tests skip when PySide6 or Kirigami is not installed (the Ubuntu jobs); with
``FASTFOTO_REQUIRE_QT=1`` (the Fedora job) a missing one fails instead of skipping.
"""

import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.gui.qt import unavailable

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")


@pytest.fixture(scope="session")
def qapp() -> Iterator[Any]:
    try:
        from PySide6.QtWidgets import QApplication

        from fastfoto_linux.gui.qt.app import configure_style
    except ImportError as error:
        unavailable(f"PySide6 is not installed ({error})")
    app = QApplication.instance() or QApplication(["fastfoto-tests"])
    configure_style()
    yield app


@pytest.fixture(scope="session")
def kirigami(qapp: Any) -> None:
    from PySide6.QtQml import QQmlEngine

    from fastfoto_linux.gui.qt.app import kirigami_available

    if not kirigami_available(QQmlEngine().importPathList()):
        unavailable("Kirigami (kf6-kirigami) is not installed")


@pytest.fixture
def messages(qapp: Any) -> Iterator[list[str]]:
    """Every Qt warning or error printed while the test runs (QML warnings included)."""
    from PySide6.QtCore import QtMsgType, qInstallMessageHandler

    seen: list[str] = []

    def handler(kind: QtMsgType, context: Any, text: str) -> None:
        if kind in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
            seen.append(text)

    previous = qInstallMessageHandler(handler)
    yield seen
    qInstallMessageHandler(previous)


@pytest.fixture
def make_bridge(qapp: Any, out: Path) -> Iterator[Callable[..., Any]]:
    """Bridges with fake discovery, session and processing; cleaned up after the test."""
    from fastfoto_linux.gui.form import ScanForm
    from fastfoto_linux.gui.qt.bridge import Bridge
    from fastfoto_linux.scanner import ScanTarget
    from tests.cli.fakes import DEVICE
    from tests.gui.helpers import ScriptedSession, process_fake

    made: list[Bridge] = []

    def make(**options: Any) -> Bridge:
        options.setdefault("form", ScanForm(output_folder=str(out)))
        options.setdefault("discover", lambda: ScanTarget(device=DEVICE))
        options.setdefault("session", ScriptedSession(out))
        options.setdefault("process", process_fake(out))
        bridge = Bridge(remember=False, **options)
        made.append(bridge)
        return bridge

    yield make
    for bridge in made:
        bridge.shutdown()
