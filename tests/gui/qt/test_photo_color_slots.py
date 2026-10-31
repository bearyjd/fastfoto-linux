"""QML calls reach the colour slots as QML sends them, so values are checked before conversion."""

import pytest

from tests.gui.qt import require_qt

require_qt()

from PySide6.QtCore import QObject
from PySide6.QtQml import QJSEngine, QQmlEngine

from tests.gui.qt.test_photo_edit_view import open_editor

pytestmark = pytest.mark.usefixtures("kirigami")
BAD = ("NaN", "Infinity", "-Infinity", "true", "false", "2.5", "'7'", "null", "undefined", "[]")
GOOD = ("30", "30.0", "0", "10")
SLOTS = (
    ("setDetail", "sharpen", "detail"),
    ("setWhiteBalance", "tint", "whiteBalance"),
    ("setTone", "contrast", "tone"),
)
MESSAGE = "Enter a whole number for this adjustment."


def call_from_qml(target: QObject, slot: str, field: str, expression: str):
    engine = QJSEngine()
    QQmlEngine.setObjectOwnership(target, QQmlEngine.ObjectOwnership.CppOwnership)
    function = engine.evaluate(f"(function (c) {{ c.{slot}('{field}', {expression}); }})")
    result = function.call([engine.newQObject(target)])
    assert not result.isError(), result.toString()


@pytest.mark.parametrize("target", SLOTS)
@pytest.mark.parametrize("expression", BAD)
def test_non_integral_qml_values_are_rejected_without_touching_the_draft(
    make_bridge, out, target, expression
):
    slot, field, prop = target
    bridge, view, _worker = open_editor(make_bridge, out)
    draft, before = bridge.controller.photo_edit.recipe, getattr(view.color, prop)
    call_from_qml(view.color, slot, field, expression)
    assert view.error == MESSAGE
    assert bridge.controller.photo_edit.recipe is draft
    assert not bridge.controller.photo_edit._undo and not bridge.controller.photo_edit.dirty
    assert getattr(view.color, prop) == before


@pytest.mark.parametrize("target", SLOTS)
@pytest.mark.parametrize("expression", GOOD)
def test_integral_qml_numbers_are_accepted(make_bridge, out, target, expression):
    slot, field, prop = target
    _bridge, view, _worker = open_editor(make_bridge, out)
    call_from_qml(view.color, slot, field, expression)
    assert not view.error
    assert getattr(view.color, prop)[field] == int(float(expression))
