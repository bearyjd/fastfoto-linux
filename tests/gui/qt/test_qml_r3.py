"""Review round 3 in the window: a click on Scan right after editing, and text that is only text."""

from pathlib import Path
from typing import Any

import pytest

from tests.gui.qt import require_qt

require_qt()

from PySide6.QtCore import QObject, QPoint, QPointF, Qt
from PySide6.QtQml import QQmlExpression
from PySide6.QtTest import QTest

from fastfoto_linux.gui.form import ScanForm
from tests.gui.helpers import ScriptedSession
from tests.gui.qt import test_bridge_disk, test_qml
from tests.gui.qt.qt_helpers import child, invoke, settle, wait_until
from tests.gui.qt.test_qml import ready

pytestmark = pytest.mark.usefixtures("kirigami")
open_window = test_qml.open_window  # the fixtures that open the window and make the disk slow
slow_disk = test_bridge_disk.slow_disk
PLAIN_TEXT = 0  # QtQuick Text.PlainText
CONTROLS = ("Button", "Chip", "ToolTip", "MenuItem", "Action", "Switch", "CheckBox", "Dialog")


def center(item: Any) -> QPoint:
    """Where the middle of an item is in its window."""
    return item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()


def press(window: Any, item: Any) -> None:
    QTest.mousePress(
        window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center(item)
    )


def release(window: Any, item: Any) -> None:
    QTest.mouseRelease(
        window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center(item)
    )


def type_slash_in_the_folder_field(window: Any, bridge: Any) -> None:
    """Edit the folder like a user: focus the field, put the cursor at its end, press a key."""
    field = child(window, "folderField")
    invoke(field, "forceActiveFocus")
    field.setProperty("cursorPosition", len(str(field.property("text"))))
    before = bridge.form["output_folder"]
    QTest.keyClick(window, Qt.Key.Key_Slash)
    wait_until(lambda: bridge.form["output_folder"] == before + "/", "the typed character")


def test_the_first_click_on_scan_after_editing_the_folder_starts_one_scan(
    make_bridge: Any, open_window: Any, slow_disk: Any, out: Path
) -> None:
    """Pressing Scan leaves the folder field, which starts a check: the press must not lose."""
    session = ScriptedSession(out)
    bridge = make_bridge(session=session)
    window, _ = open_window(bridge)
    slow_disk.gate.set()
    ready(bridge)
    settle()
    slow_disk.gate.clear()  # from here on the disk answers when the test says so
    type_slash_in_the_folder_field(window, bridge)
    scan = child(window, "scanButton")
    assert scan.property("enabled") is True
    checks = len(slow_disk.threads)

    press(window, scan)
    wait_until(lambda: len(slow_disk.threads) > checks, "leaving the field to check the folder")
    assert scan.property("enabled") is True  # the check under way did not take the button away
    release(window, scan)
    wait_until(lambda: bridge.startingScan, "the click to reach the bridge")
    assert session.requests == []  # it waits for the folder

    slow_disk.gate.set()
    wait_until(lambda: bridge.state == "done", "the scan to finish")
    settle()
    assert len(session.requests) == 1


def test_a_click_on_scan_with_nothing_edited_starts_one_scan(
    make_bridge: Any, open_window: Any, slow_disk: Any, out: Path
) -> None:
    session = ScriptedSession(out)
    bridge = make_bridge(session=session)
    window, _ = open_window(bridge)
    slow_disk.gate.set()
    ready(bridge)
    settle()
    slow_disk.gate.clear()
    scan = child(window, "scanButton")

    press(window, scan)
    release(window, scan)
    wait_until(lambda: bridge.startingScan, "the click to reach the bridge")
    slow_disk.gate.set()
    wait_until(lambda: bridge.state == "done", "the scan to finish")
    settle()
    assert len(session.requests) == 1


def test_a_click_after_editing_into_a_folder_that_is_gone_starts_no_scan_and_says_why(
    make_bridge: Any, open_window: Any, slow_disk: Any, out: Path
) -> None:
    session = ScriptedSession(out)
    bridge = make_bridge(session=session)
    window, _ = open_window(bridge)
    slow_disk.gate.set()
    ready(bridge)
    settle()
    slow_disk.gate.clear()
    type_slash_in_the_folder_field(window, bridge)
    bridge.setField("output_folder", str(out / "gone"))  # what the field now says
    scan = child(window, "scanButton")

    press(window, scan)
    release(window, scan)
    wait_until(lambda: bridge.startingScan, "the click to reach the bridge")
    slow_disk.gate.set()
    wait_until(lambda: not bridge.busy, "the folder check to answer")
    settle()
    assert session.requests == []
    assert "output_folder" in bridge.errors
    assert child(window, "folderError").property("visible") is True


def text_format(item: Any) -> int:
    """A Text item's textFormat (PySide cannot convert the enum through ``property()``)."""
    from PySide6.QtQml import QQmlEngine

    value, failed = QQmlExpression(QQmlEngine.contextForObject(item), item, "textFormat").evaluate()
    assert not failed
    return int(value)


def control_texts(window: Any) -> dict[str, str]:
    """The text of every button, chip, tooltip, menu item, action and switch of the window."""
    found: dict[str, str] = {}
    for item in window.findChildren(QObject):
        kind = item.metaObject().className()
        text = item.property("text")
        if isinstance(text, str) and any(word in kind for word in CONTROLS):
            found[item.objectName() or kind] = text
    return found


def test_a_folder_name_with_markup_is_plain_text_next_to_the_process_button(
    make_bridge: Any, open_window: Any, out: Path
) -> None:
    """QQC2.Button has no textFormat, and ``<img ...>`` in a label crashes the Basic style."""
    hostile = out / "<img src=x width=9999>"
    hostile.mkdir()
    session = ScriptedSession(hostile, hold=True)
    bridge = make_bridge(form=ScanForm(output_folder=str(hostile)), session=session)
    window, warnings = open_window(bridge)
    ready(bridge)
    bridge.startScan()
    wait_until(lambda: bridge.canCancel, "the scan to hold")
    bridge.cancel()
    wait_until(lambda: bridge.canProcessKept, "the offer")
    settle()

    button = child(window, "processKeptButton")
    assert button.property("text") == "Process them now"
    destination = child(window, "processKeptFolder")
    assert str(hostile) in destination.property("text")
    assert text_format(destination) == PLAIN_TEXT
    for name, text in control_texts(window).items():
        assert "<img" not in text, f"{name} carries the folder name as it is typed"
    assert warnings == []
