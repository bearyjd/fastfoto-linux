"""The export preset drop-downs in the window: entries, default, link to the form."""

from typing import Any

import pytest

from tests.gui.qt import require_qt

require_qt()

from PySide6.QtCore import Q_ARG, QMetaObject

from tests.gui.qt import test_qml_documents
from tests.gui.qt.qt_helpers import child, settle

pytestmark = pytest.mark.usefixtures("kirigami", "ocrmypdf_comes_with_the_app")
open_window = test_qml_documents.open_window
make_doc_bridge = test_qml_documents.make_doc_bridge
VALUES = ["", "high-quality", "small", "lossless"]


def values(box: Any) -> list[str]:
    return [entry["value"] for entry in box.property("model")]


def pick(box: Any, index: int) -> None:
    box.setProperty("currentIndex", index)
    assert QMetaObject.invokeMethod(box, "activated", Q_ARG(int, index))
    settle()


def test_the_documents_box_offers_standard_first_and_sets_the_field(
    make_doc_bridge: Any, open_window: Any
) -> None:
    bridge = make_doc_bridge()
    window, warnings = open_window(bridge)
    box = child(window, "docPresetBox")
    assert values(box) == VALUES
    assert box.property("currentValue") == "" and box.property("currentText") == "Standard"
    pick(box, 2)
    assert bridge.controller.document_form.preset == "small"
    bridge.setDocumentField("preset", "lossless")
    settle()
    assert box.property("currentValue") == "lossless"
    assert warnings == []


def test_the_photos_box_offers_standard_first_and_sets_the_field(
    make_bridge: Any, open_window: Any
) -> None:
    bridge = make_bridge()
    window, warnings = open_window(bridge)
    box = child(window, "presetBox")
    assert values(box) == VALUES
    assert box.property("currentText") == "Standard"
    pick(box, 3)
    assert bridge.form["preset"] == "lossless"
    bridge.setField("preset", "")
    settle()
    assert box.property("currentValue") == ""
    assert warnings == []


def test_a_bad_value_through_the_slot_leaves_the_form_alone(
    make_bridge: Any, open_window: Any
) -> None:
    bridge = make_bridge()
    open_window(bridge)
    bridge.setField("preset", "Small")
    bridge.setField("preset", True)
    assert bridge.form["preset"] == ""
