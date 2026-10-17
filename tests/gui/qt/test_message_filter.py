"""The Qt message handler hides the two known KDE lines in a real Qt, and only those."""

import os
from pathlib import Path
from typing import Any

import pytest

from tests.gui.qt import require_qt

require_qt()

from PySide6.QtCore import QLoggingCategory, QMessageLogContext, QtMsgType, QUrl, qCWarning
from PySide6.QtQml import QQmlComponent, QQmlEngine

from fastfoto_linux.gui.qt import messages as message_filter
from fastfoto_linux.session.raw import TEMP_PREFIX

SHORTCUT_TEXT = (
    "Only binding to one of multiple key bindings associated with 9. "
    "Use 'sequences: [ <key> ]' to bind to all of them."
)
KDIRMODEL = "kf.kio.widgets.kdirmodel"


def removed(folder: str) -> str:
    return f'No node found for item that was just removed: QUrl("file:///photos/album/{folder}")'


def warn_from_qml(path: Path, text: str) -> None:
    """Print ``text`` as a QML warning coming from the file ``path``, as KDE's style does."""
    path.parent.mkdir(parents=True, exist_ok=True)
    source = f'import QtQml\nQtObject {{ Component.onCompleted: console.warn("{text}") }}\n'
    path.write_text(source, encoding="utf-8")
    engine = QQmlEngine()
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(path)))
    created = component.create()
    assert created is not None, component.errorString()
    created.deleteLater()


def warn_in_category(name: str, text: str) -> None:
    qCWarning(QLoggingCategory(name), text)


def test_the_two_known_lines_are_hidden_and_the_rest_reaches_the_previous_handler(
    qapp: Any, messages: list[str], tmp_path: Path
) -> None:
    undo = message_filter.install_message_filter()
    try:
        warn_from_qml(tmp_path / "org" / "kde" / "desktop" / "MenuItem.qml", SHORTCUT_TEXT)
        warn_from_qml(tmp_path / "org" / "kde" / "desktop" / "Button.qml", SHORTCUT_TEXT)
        warn_in_category(KDIRMODEL, removed(f"{TEMP_PREFIX}ab12cd"))
        warn_in_category(KDIRMODEL, removed("Holiday"))
        warn_in_category("fastfoto.test", "something else broke")
    finally:
        undo()
    assert messages == [SHORTCUT_TEXT, removed("Holiday"), "something else broke"]


def test_undoing_the_filter_puts_the_previous_handler_back(qapp: Any, messages: list[str]) -> None:
    message_filter.install_message_filter()()
    warn_in_category(KDIRMODEL, removed(f"{TEMP_PREFIX}ab12cd"))
    assert messages == [removed(f"{TEMP_PREFIX}ab12cd")]


def test_without_a_previous_handler_the_rest_goes_to_stderr_in_qts_default_format(
    qapp: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    undo = message_filter.install_message_filter()
    try:
        warn_in_category(KDIRMODEL, removed(f"{TEMP_PREFIX}ab12cd"))
        assert capsys.readouterr().err == ""
        warn_in_category("fastfoto.test", "something else broke")
        assert capsys.readouterr().err == "fastfoto.test: something else broke\n"
    finally:
        undo()


def test_a_fatal_message_still_ends_the_process(
    qapp: Any, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    aborted: list[bool] = []
    monkeypatch.setattr(os, "abort", lambda: aborted.append(True))
    handler = message_filter.filtering_handler(None)
    handler(QtMsgType.QtFatalMsg, QMessageLogContext(), "cannot go on")
    assert aborted == [True]
    assert "cannot go on" in capsys.readouterr().err
