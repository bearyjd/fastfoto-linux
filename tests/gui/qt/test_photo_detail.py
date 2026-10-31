"""Denoise and sharpen sliders in the real photo editor page."""

from types import SimpleNamespace

import pytest

from tests.gui.qt import require_qt

require_qt()

from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from tests.gui.qt import test_qml
from tests.gui.qt.qt_helpers import child, invoke, settle
from tests.gui.qt.test_photo_edit_view import open_editor
from tests.gui.qt.test_photo_tone import ready_page
from tests.gui.qt.test_qml_r4 import PLAIN_TEXT, enum_property

open_window = test_qml.open_window
pytestmark = pytest.mark.usefixtures("kirigami")
NEUTRAL = dict(denoise_luma=0, denoise_chroma=0, sharpen=0)
CONTROLS = {
    "photoDetailDenoiseLuma": ("denoise_luma", "Noise reduction"),
    "photoDetailDenoiseChroma": ("denoise_chroma", "Colour noise"),
    "photoDetailSharpen": ("sharpen", "Sharpen"),
}
HINT = (
    "Optional and off by default. Computed at full resolution, so large scans can be slow to "
    "preview. The fitted preview shows sharpening only faintly."
)


def test_color_child_contract_and_slot(make_bridge, out):
    _bridge, view, _worker = open_editor(make_bridge, out)
    meta = view.color.metaObject()
    assert meta.indexOfProperty("detail") >= 0
    assert meta.indexOfSlot("setDetail(QString,int)") >= 0
    assert view.color.detail == NEUTRAL


def test_slot_changes_values_refreshes_and_reports_user_errors(make_bridge, out):
    bridge, view, _worker = open_editor(make_bridge, out)
    seen = []
    view.color.changed.connect(lambda: seen.append(1))
    view.color.setDetail("sharpen", 40)
    assert view.color.detail == dict(NEUTRAL, sharpen=40) and seen
    draft = bridge.controller.photo_edit.recipe
    view.color.setDetail("temperature", 1)
    assert view.error == "Choose a noise reduction or sharpening adjustment."
    view.color.setDetail("denoise_luma", 101)
    assert view.error and "/" not in view.error
    assert bridge.controller.photo_edit.recipe is draft
    view.undo()
    assert view.color.detail == NEUTRAL


def test_real_page_controls_exist_with_ranges_labels_and_hint(make_bridge, open_window, out):
    bridge, _view, _worker = open_editor(make_bridge, out, candidates=())
    window, warnings = open_window(bridge)
    page = ready_page(window)
    for name, (_field, label) in CONTROLS.items():
        slider = child(page, name)
        assert (slider.property("from"), slider.property("to")) == (0, 100)
        assert slider.property("stepSize") == 1 and slider.property("value") == 0
        assert slider.property("enabled")
        assert child(page, name + "Label").property("text") == label
        assert enum_property(child(page, name + "Label"), "textFormat") == PLAIN_TEXT
    assert child(page, "photoDetailHeading").property("text") == "Detail"
    assert child(page, "photoDetailHint").property("text") == HINT
    assert enum_property(child(page, "photoDetailHint"), "textFormat") == PLAIN_TEXT
    assert warnings == []


def test_each_slider_moved_calls_set_detail_for_its_own_field(make_bridge, open_window, out):
    bridge, view, _worker = open_editor(make_bridge, out, candidates=())
    window, warnings = open_window(bridge)
    window.setHeight(2400)
    page = ready_page(window)
    for name in CONTROLS:
        invoke(child(page, name), "moved")
        settle()
    assert view.color.detail == NEUTRAL
    for name, (field, _label) in CONTROLS.items():
        slider = child(page, name)
        slider.setProperty("value", 20)
        invoke(slider, "moved")
        settle()
        assert view.color.detail[field] == 20, name
        assert sum(view.color.detail.values()) == 20
        view.color.setDetail(field, 0)
        settle()
    assert warnings == []


def test_slider_drag_is_one_undo_and_follows_the_draft(make_bridge, open_window, out):
    bridge, view, _worker = open_editor(make_bridge, out, candidates=())
    window, warnings = open_window(bridge)
    window.setHeight(2400)
    page = ready_page(window)
    slider = child(page, "photoDetailSharpen")
    initial = bridge.controller.photo_edit.recipe
    start = slider.mapToScene(QPointF(slider.width() * 0.2, slider.height() / 2)).toPoint()
    end = slider.mapToScene(QPointF(slider.width() * 0.7, slider.height() / 2)).toPoint()
    QTest.mousePress(window, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(window, end, delay=20)
    QTest.mouseRelease(window, Qt.MouseButton.LeftButton, pos=end)
    settle()
    assert view.color.detail["sharpen"] > 0
    assert slider.property("value") == view.color.detail["sharpen"]
    assert len(bridge.controller.photo_edit._undo) == 1
    view.undo()
    assert bridge.controller.photo_edit.recipe is initial
    assert slider.property("value") == 0 and warnings == []


def test_reset_adjustments_clears_detail_in_one_undo_step(make_bridge, open_window, out):
    bridge, view, _worker = open_editor(make_bridge, out, candidates=())
    window, warnings = open_window(bridge)
    page = ready_page(window)
    view.color.setTone("contrast", 10)
    view.color.setDetail("denoise_chroma", 30)
    view.color.setDetail("sharpen", 45)
    settle()
    adjusted, depth = bridge.controller.photo_edit.recipe, len(bridge.controller.photo_edit._undo)
    invoke(child(page, "photoResetTone"), "clicked")
    settle()
    assert view.color.detail == NEUTRAL
    assert child(page, "photoDetailSharpen").property("value") == 0
    assert child(page, "photoDetailDenoiseChroma").property("value") == 0
    assert len(bridge.controller.photo_edit._undo) == depth + 1
    view.undo()
    assert bridge.controller.photo_edit.recipe is adjusted
    assert child(page, "photoDetailSharpen").property("value") == 45
    assert warnings == []


def test_controls_are_disabled_when_editing_is_blocked(make_bridge, open_window, out):
    bridge, view, _worker = open_editor(make_bridge, out, candidates=())
    window, warnings = open_window(bridge)
    page = ready_page(window)
    bridge.controller.photo_edit._inflight = SimpleNamespace(operation="save")
    view.refresh()
    settle()
    assert not view.canEdit
    for name in CONTROLS:
        assert not child(page, name).property("enabled"), name
    assert warnings == []
