"""The language toggle is seen and reachable by a real mouse or keyboard, not just click()."""

from typing import Any

import pytest

from tests.gui.qt import require_qt

require_qt()

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest

from tests.gui.qt import test_qml_documents
from tests.gui.qt.qt_helpers import child, settle

pytestmark = pytest.mark.usefixtures("kirigami", "ocrmypdf_comes_with_the_app")
open_window = test_qml_documents.open_window
make_doc_bridge = test_qml_documents.make_doc_bridge

TALL = 2400  # tall enough that the form needs no scrolling to show the picker


def show(window: Any, width: int | None = None) -> tuple[Any, Any]:
    window.setHeight(TALL)
    window.setWidth(int(width or window.property("minimumWidth")))
    settle()
    return child(window, "docLanguagePicker"), child(window, "docLanguageToggle")


def centre(window: Any, item: QQuickItem) -> QPoint:
    point = item.mapToScene(item.boundingRect().center())
    assert 0 <= point.y() < window.height(), "the item is scrolled out of the window"
    return QPoint(int(point.x()), int(point.y()))


def distinct_colours(window: Any, item: QQuickItem) -> int:
    """How many colours are painted over the item: one means it is blank."""
    image: QImage = window.grabWindow()
    top_left = item.mapToScene(item.boundingRect().topLeft())
    colours = {
        image.pixel(int(top_left.x()) + dx, int(top_left.y()) + dy)
        for dx in range(int(item.width()))
        for dy in range(int(item.height()))
    }
    return len(colours)


def test_the_toggle_paints_its_text_so_it_cannot_be_an_invisible_icon(
    make_doc_bridge: Any, open_window: Any
) -> None:
    window, _ = open_window(make_doc_bridge())
    for width in (None, 1024):
        _, toggle = show(window, width)
        assert toggle.property("visible") and toggle.width() > 0 and toggle.height() > 0
        assert toggle.width() > 80, "an icon-only button vanishes when the icon theme lacks it"
        assert distinct_colours(window, toggle) > 4


@pytest.mark.parametrize("width", [None, 900, 1400])
def test_a_real_mouse_click_on_the_toggle_expands_and_collapses_the_list(
    make_doc_bridge: Any, open_window: Any, width: int | None
) -> None:
    window, _ = open_window(make_doc_bridge())
    picker, toggle = show(window, width)
    assert toggle.x() >= 0 and toggle.x() + toggle.width() <= picker.width() + 1
    QTest.mouseClick(
        window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, centre(window, toggle)
    )
    settle()
    assert picker.property("expanded") is True
    assert child(window, "docLanguageScroll").property("visible")
    QTest.mouseClick(
        window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, centre(window, toggle)
    )
    settle()
    assert picker.property("expanded") is False


def test_clicking_the_summary_text_also_toggles(make_doc_bridge: Any, open_window: Any) -> None:
    window, _ = open_window(make_doc_bridge())
    picker, _ = show(window)
    summary = child(window, "docLanguageSummary")
    QTest.mouseClick(
        window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, centre(window, summary)
    )
    settle()
    assert picker.property("expanded") is True


def test_the_toggle_takes_keyboard_focus_and_opens_with_space(
    make_doc_bridge: Any, open_window: Any
) -> None:
    window, _ = open_window(make_doc_bridge())
    picker, toggle = show(window)
    assert toggle.property("activeFocusOnTab") is True
    toggle.forceActiveFocus()
    settle()
    QTest.keyClick(window, Qt.Key.Key_Space)
    settle()
    assert picker.property("expanded") is True


def test_the_open_list_survives_a_form_refresh(make_doc_bridge: Any, open_window: Any) -> None:
    bridge = make_doc_bridge()
    window, _ = open_window(bridge)
    picker, toggle = show(window)
    QTest.mouseClick(
        window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, centre(window, toggle)
    )
    settle()
    assert picker.property("expanded") is True
    bridge.setDocumentField("searchable", False)
    bridge.setDocumentField("searchable", True)
    settle()
    assert child(window, "docLanguagePicker") is picker
    assert picker.property("expanded") is True
