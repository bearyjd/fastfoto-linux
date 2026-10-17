"""The "Loaded" drop-down of the Photos form, in the window: the entries, the default, the link."""

from typing import Any

import pytest

from tests.gui.qt import require_qt

require_qt()

from PySide6.QtCore import Q_ARG, QMetaObject

from tests.gui.qt import test_qml
from tests.gui.qt.qt_helpers import child, settle

pytestmark = pytest.mark.usefixtures("kirigami")
open_window = test_qml.open_window  # the fixture that opens the window

FACE_UP_ENTRY = ("Face up (back first)", "face-up")
FACE_DOWN_ENTRY = ("Face down (front first)", "face-down")


def entries(box: Any) -> list[tuple[str, str]]:
    return [(entry["text"], entry["value"]) for entry in box.property("model")]


def test_the_loaded_box_offers_face_up_then_face_down_and_starts_on_face_up(
    make_bridge: Any, open_window: Any
) -> None:
    window, warnings = open_window(make_bridge())
    box = child(window, "feedBox")
    assert entries(box) == [FACE_UP_ENTRY, FACE_DOWN_ENTRY]
    assert (box.property("currentText"), box.property("currentValue")) == FACE_UP_ENTRY
    assert warnings == []


def test_the_loaded_box_follows_the_form(make_bridge: Any, open_window: Any) -> None:
    bridge = make_bridge()
    window, _ = open_window(bridge)
    box = child(window, "feedBox")
    bridge.setField("loaded", "face-down")
    settle()
    assert (box.property("currentText"), box.property("currentValue")) == FACE_DOWN_ENTRY
    bridge.setField("loaded", "face-up")
    settle()
    assert (box.property("currentText"), box.property("currentValue")) == FACE_UP_ENTRY


def test_picking_face_down_in_the_box_sets_the_form(make_bridge: Any, open_window: Any) -> None:
    bridge = make_bridge()
    window, _ = open_window(bridge)
    box = child(window, "feedBox")
    box.setProperty("currentIndex", 1)  # what a click on the second entry does ...
    assert QMetaObject.invokeMethod(box, "activated", Q_ARG(int, 1))  # ... then it says so
    settle()
    assert bridge.form["loaded"] == "face-down"
