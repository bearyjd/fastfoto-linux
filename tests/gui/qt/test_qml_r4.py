"""Review round 1 of the Documents PR in the window: the loading hints, and a quieter option."""

from typing import Any

import pytest

from tests.gui.qt import require_qt

require_qt()

from PySide6.QtCore import QPointF
from PySide6.QtQml import QQmlEngine, QQmlExpression

from tests.gui.qt import test_qml_documents
from tests.gui.qt.qt_helpers import child, settle
from tests.gui.qt.test_qml_documents import shown

pytestmark = pytest.mark.usefixtures("kirigami")
open_window = test_qml_documents.open_window  # the fixtures that open the window
make_doc_bridge = test_qml_documents.make_doc_bridge

PLAIN_TEXT = 0  # QtQuick Text.PlainText
NO_WRAP = 0  # QtQuick Text.NoWrap
PHOTOS_HINT = "Load photos face up, top edge first"
DOCUMENTS_HINT = "Load pages face down, top edge first"


def enum_property(item: Any, name: str) -> int:
    """A Text item's enum property (PySide cannot convert these through ``property()``)."""
    value, failed = QQmlExpression(QQmlEngine.contextForObject(item), item, name).evaluate()
    assert not failed
    return int(value)


def top_left(item: Any) -> QPointF:
    return item.mapToScene(QPointF(0, 0))


def test_each_form_says_how_to_load_the_scanner_as_its_own_label_does(
    make_doc_bridge: Any, open_window: Any, messages: list[str]
) -> None:
    bridge = make_doc_bridge(mode="photos")
    window, warnings = open_window(bridge)
    assert child(window, "photosLoadHint").property("text") == PHOTOS_HINT
    assert child(window, "documentsLoadHint").property("text") == DOCUMENTS_HINT
    assert shown(window, "photosLoadHint") and not shown(window, "documentsLoadHint")
    bridge.setMode("documents")
    settle()
    assert shown(window, "documentsLoadHint") and not shown(window, "photosLoadHint")
    bridge.setMode("photos")
    settle()
    assert shown(window, "photosLoadHint")
    assert warnings == []
    assert messages == []


def test_the_hints_are_plain_text_the_user_can_read_in_both_modes(
    make_doc_bridge: Any, open_window: Any
) -> None:
    bridge = make_doc_bridge()
    window, _ = open_window(bridge)
    for name in ("photosLoadHint", "documentsLoadHint"):
        hint = child(window, name)
        assert enum_property(hint, "textFormat") == PLAIN_TEXT
        assert enum_property(hint, "wrapMode") != NO_WRAP  # wraps in a narrow window


def test_keep_blank_pages_is_set_in_below_both_sides(
    make_doc_bridge: Any, open_window: Any
) -> None:
    bridge = make_doc_bridge()
    window, _ = open_window(bridge)
    both, keep = child(window, "docBothSidesBox"), child(window, "docKeepBlankBox")
    assert top_left(keep).y() > top_left(both).y()  # still under "Both sides" ...
    assert top_left(keep).x() > top_left(both).x()  # ... but set in, as a detail of it
    assert keep.property("text") == "Keep blank pages"
