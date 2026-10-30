"""White balance sliders and preset buttons in the real photo editor page."""

from types import SimpleNamespace

import pytest

from tests.gui.qt import require_qt

require_qt()

from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from fastfoto_linux.gui.photoeditpresets import PRESETS
from tests.gui.qt import test_qml
from tests.gui.qt.qt_helpers import child, click, invoke, settle
from tests.gui.qt.test_photo_edit_view import open_editor
from tests.gui.qt.test_photo_tone import ready_page

open_window = test_qml.open_window
pytestmark = pytest.mark.usefixtures("kirigami")
NEUTRAL = dict(temperature=0, tint=0)
HINT = (
    "Temperature: lower is cooler (blue), higher is warmer (yellow). "
    "Tint: lower is greener, higher is more magenta."
)


def names(obj):
    meta = obj.metaObject()
    return {meta.property(i).name() for i in range(meta.propertyCount())}


def test_color_child_contract_and_slots(make_bridge, out):
    _bridge, view, _worker = open_editor(make_bridge, out)
    color = view.color
    assert {"whiteBalance", "presets", "activePreset", "tone"} <= names(color)
    assert color.whiteBalance == NEUTRAL and color.activePreset == ""
    assert color.presets == [dict(id=p.id, label=p.label) for p in PRESETS]
    meta = color.metaObject()
    for slot in ("setWhiteBalance(QString,int)", "applyPreset(QString)"):
        assert meta.indexOfSlot(slot) >= 0, slot


def test_slots_change_values_refresh_and_report_user_errors(make_bridge, out):
    bridge, view, _worker = open_editor(make_bridge, out)
    seen = []
    view.color.changed.connect(lambda: seen.append(1))
    view.color.setWhiteBalance("temperature", 30)
    assert view.color.whiteBalance == dict(temperature=30, tint=0) and seen
    draft = bridge.controller.photo_edit.recipe
    view.color.setWhiteBalance("hue", 1)
    assert view.error == "Choose a temperature or tint adjustment."
    view.color.setWhiteBalance("tint", 101)
    assert view.error and "/" not in view.error
    assert bridge.controller.photo_edit.recipe is draft
    view.color.applyPreset("sepia")
    assert view.error == "Choose a listed preset."
    view.color.applyPreset("warm")
    assert not view.error and view.color.activePreset == "warm"
    view.undo()
    assert view.color.whiteBalance == dict(temperature=30, tint=0)


def test_real_page_controls_exist_with_ranges_and_hint(make_bridge, open_window, out):
    bridge, view, _worker = open_editor(make_bridge, out, candidates=())
    window, warnings = open_window(bridge)
    page = ready_page(window)
    for field in ("temperature", "tint"):
        slider = child(page, "photoWhiteBalance" + field.capitalize())
        assert (slider.property("from"), slider.property("to")) == (-100, 100)
        assert slider.property("stepSize") == 1 and slider.property("value") == 0
        assert slider.property("enabled")
        assert slider.property("snapMode") == 2  # SnapAlways
    assert child(page, "photoWhiteBalanceTemperatureLabel").property("text") == "Temperature"
    assert child(page, "photoWhiteBalanceTintLabel").property("text") == "Tint"
    assert child(page, "photoWhiteBalanceHint").property("text") == HINT
    assert child(page, "photoWhiteBalanceHint").property("textFormat") == Qt.TextFormat.PlainText
    for item in PRESETS:
        button = child(page, "photoPreset" + item.id.capitalize())
        assert button.property("text") == item.label
        assert button.property("enabled") and not button.property("checkable")
        assert not button.property("highlighted")
    assert warnings == []


def test_slider_moved_calls_set_white_balance_and_drag_is_one_undo(make_bridge, open_window, out):
    bridge, view, _worker = open_editor(make_bridge, out, candidates=())
    window, warnings = open_window(bridge)
    window.setHeight(1800)
    page = ready_page(window)
    slider = child(page, "photoWhiteBalanceTemperature")
    initial = bridge.controller.photo_edit.recipe
    start = slider.mapToScene(QPointF(slider.width() * 0.4, slider.height() / 2)).toPoint()
    end = slider.mapToScene(QPointF(slider.width() * 0.8, slider.height() / 2)).toPoint()
    QTest.mousePress(window, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(window, end, delay=20)
    QTest.mouseRelease(window, Qt.MouseButton.LeftButton, pos=end)
    settle()
    assert view.color.whiteBalance["temperature"] > 0
    assert slider.property("value") == view.color.whiteBalance["temperature"]
    assert len(bridge.controller.photo_edit._undo) == 1
    view.undo()
    assert bridge.controller.photo_edit.recipe is initial
    assert slider.property("value") == 0 and warnings == []


def test_preset_click_changes_values_and_highlight_follows(make_bridge, open_window, out):
    bridge, view, _worker = open_editor(make_bridge, out, candidates=())
    window, warnings = open_window(bridge)
    page = ready_page(window)
    click(child(page, "photoPresetCool"))
    settle()
    assert view.color.whiteBalance == dict(temperature=-25, tint=0)
    assert view.color.activePreset == "cool"
    assert child(page, "photoPresetCool").property("highlighted")
    assert not child(page, "photoPresetWarm").property("highlighted")
    assert child(page, "photoWhiteBalanceTemperature").property("value") == -25
    view.color.setWhiteBalance("tint", 3)
    settle()
    assert not child(page, "photoPresetCool").property("highlighted")
    invoke(child(page, "photoResetTone"), "clicked")
    settle()
    assert view.color.whiteBalance == NEUTRAL
    assert not any(child(page, "photoPreset" + p.id.capitalize()).property("highlighted")
                   for p in PRESETS)
    assert warnings == []


def test_controls_are_disabled_when_editing_is_blocked(make_bridge, open_window, out):
    bridge, view, _worker = open_editor(make_bridge, out, candidates=())
    window, warnings = open_window(bridge)
    page = ready_page(window)
    bridge.controller.photo_edit._inflight = SimpleNamespace(operation="save")
    view.refresh()
    settle()
    assert not view.canEdit
    for name in (
        "photoWhiteBalanceTemperature",
        "photoWhiteBalanceTint",
        *("photoPreset" + p.id.capitalize() for p in PRESETS),
    ):
        assert not child(page, name).property("enabled"), name
    assert warnings == []
