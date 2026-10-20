"""Geometry properties and the real QML crop, rotate and result controls."""

from dataclasses import replace

import pytest

from tests.gui.qt import require_qt

require_qt()

from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from tests.gui.qt import test_qml
from tests.gui.qt.qt_helpers import child, click, invoke, settle
from tests.gui.qt.test_photo_edit_view import open_editor
from tests.gui.qt.test_photo_tone import ready_page

open_window = test_qml.open_window
pytestmark = pytest.mark.usefixtures("kirigami")
FULL = [0, 0, 100, 60]


def editor_page(make_bridge, open_window, out, **kwargs):
    # 100 dpi makes the minimum crop 20 px, so 100 x 60 synthetic scans can be cropped.
    bridge, view, _worker = open_editor(make_bridge, out, dpi=100, **kwargs)
    window, warnings = open_window(bridge)
    window.setHeight(1800)
    return bridge, view, window, ready_page(window), warnings


def enter_mode(page):
    click(child(page, "photoGeometryMode"))
    settle()


def canvas_point(page, fx, fy):
    canvas = child(page, "photoEditCanvas")
    picture = child(page, "photoCanvasImage")
    left = (picture.width() - picture.property("paintedWidth")) / 2
    top = (picture.height() - picture.property("paintedHeight")) / 2
    x = left + fx * picture.property("paintedWidth")
    y = top + fy * picture.property("paintedHeight")
    return canvas.mapToScene(QPointF(x, y)).toPoint()


def drag(window, start, end):
    QTest.mousePress(window, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(window, end, delay=20)
    QTest.mouseRelease(window, Qt.MouseButton.LeftButton, pos=end)
    settle()


def test_view_exposes_the_geometry_contract(make_bridge, out):
    _bridge, view, _worker = open_editor(make_bridge, out)
    meta = view.metaObject()
    names = {meta.property(i).name() for i in range(meta.propertyCount())}
    assert {
        "geometryMode",
        "geometryNeutral",
        "canEditEyes",
        "geometry",
        "outputWidth",
        "outputHeight",
        "minCropWidth",
        "minCropHeight",
        "workingUrl",
    } <= names
    for slot in (
        "setGeometryMode(bool)",
        "rotateClockwise()",
        "rotateCounterclockwise()",
        "setCrop(int,int,int,int)",
        "clearCrop()",
        "resetGeometry()",
    ):
        assert meta.indexOfSlot(slot) >= 0, slot
    assert view.geometryMode is False and view.geometryNeutral is True
    assert view.canEditEyes is True
    assert view.geometry == {"quarterTurns": 0, "cropped": False, "crop": FULL}
    assert (view.outputWidth, view.outputHeight) == (100, 60)
    assert view.minCropWidth == view.minCropHeight == 59


def test_view_slots_drive_mode_rotation_crop_reset_and_undo(make_bridge, out):
    bridge, view, _worker = open_editor(make_bridge, out, dpi=100)
    side = bridge.controller.photo_edit
    view.setGeometryMode(True)
    assert view.geometryMode and not view.canEditEyes and not side.dirty
    view.rotateClockwise()
    assert view.geometry["quarterTurns"] == 1 and not view.geometryNeutral
    assert (view.outputWidth, view.outputHeight) == (60, 100)
    view.rotateCounterclockwise()
    view.rotateCounterclockwise()
    assert view.geometry["quarterTurns"] == 3
    view.setCrop(10, 0, 90, 60)
    assert view.geometry["cropped"] and view.geometry["crop"] == [10, 0, 90, 60]
    assert (view.outputWidth, view.outputHeight) == (60, 80)
    view.clearCrop()
    assert view.geometry["crop"] == FULL and not view.geometry["cropped"]
    view.resetGeometry()
    assert view.geometryNeutral
    view.undo()
    assert view.geometry["cropped"] is False and view.geometry["quarterTurns"] == 3
    view.setGeometryMode(False)
    assert view.canEditEyes


def test_view_reports_errors_for_blocked_and_invalid_actions_and_keeps_the_draft(make_bridge, out):
    bridge, view, _worker = open_editor(make_bridge, out, dpi=100)
    draft = bridge.controller.photo_edit.recipe
    view.rotateClockwise()
    assert view.error and bridge.controller.photo_edit.recipe is draft
    view.setGeometryMode(True)
    view.setCrop(10, 10, 12, 50)
    assert view.error and bridge.controller.photo_edit.recipe is draft
    view.setGeometryMode(True)
    view.setAccepted("left", True)
    assert "Crop and rotate" in view.error
    assert not view.candidates[0]["accepted"]


def test_working_url_falls_back_to_after_and_prefers_the_working_image(make_bridge, out):
    bridge, view, _worker = open_editor(make_bridge, out)
    assert view.workingUrl == view.afterUrl != ""
    side = bridge.controller.photo_edit
    working = out / "working-extra.png"
    working.write_bytes(side.preview.after.read_bytes())
    side.preview = replace(side.preview, working=working)
    view.refresh()
    assert view.workingUrl.endswith("working-extra.png") and view.workingUrl != view.afterUrl


def test_mode_button_hides_eye_markers_and_disables_eye_controls(make_bridge, open_window, out):
    _bridge, view, _window, page, warnings = editor_page(make_bridge, open_window, out)

    def markers():
        picture = child(page, "photoCanvasImage")
        return [i for i in picture.childItems() if i.objectName() == "photoEyeMarker"]

    eye_controls = ("photoEyeList", "photoAccept", "photoReject", "photoManualEye", "photoStrength")
    assert len(markers()) == 2 and all(m.isVisible() for m in markers())
    assert all(child(page, name).property("enabled") for name in eye_controls)
    assert not child(page, "photoRotateRight").property("visible")
    enter_mode(page)
    assert view.geometryMode and child(page, "photoGeometryMode").property("checked")
    assert not any(m.isVisible() for m in markers())
    assert not any(child(page, name).property("enabled") for name in eye_controls)
    assert not child(page, "photoRemoveEye").property("enabled")
    assert child(page, "photoRotateRight").property("visible")
    assert child(page, "photoBeforeAfter").property("enabled")
    enter_mode(page)
    assert not view.geometryMode
    assert len(markers()) == 2 and all(m.isVisible() for m in markers())
    assert all(child(page, name).property("enabled") for name in eye_controls)
    assert warnings == []


def test_rotate_buttons_call_the_slots_and_size_label_follows(make_bridge, open_window, out):
    bridge, view, _window, page, warnings = editor_page(make_bridge, open_window, out)
    enter_mode(page)
    label = child(page, "photoOutputSize")
    assert label.property("text") == "Saved size 100 \u00d7 60 px"
    click(child(page, "photoRotateRight"))
    assert view.geometry["quarterTurns"] == 1
    assert label.property("text") == "Saved size 60 \u00d7 100 px"
    click(child(page, "photoRotateLeft"))
    click(child(page, "photoRotateLeft"))
    assert view.geometry["quarterTurns"] == 3
    assert bridge.controller.photo_edit.recipe.schema_version == 3
    for _ in range(3):
        view.undo()
    assert view.geometryNeutral and not view.canUndo
    assert bridge.controller.photo_edit.recipe.schema_version == 2
    assert warnings == []


def test_dragging_on_the_canvas_sets_the_source_crop_as_one_undo(make_bridge, open_window, out):
    bridge, view, window, page, warnings = editor_page(make_bridge, open_window, out)
    enter_mode(page)
    initial = bridge.controller.photo_edit.recipe
    drag(window, canvas_point(page, 0.1, 0.0), canvas_point(page, 0.9, 1.0))
    # The pointer maps through whole window pixels, so allow one pixel of slack.
    left, top, right, bottom = view.geometry["crop"]
    assert 9 <= left <= 11 and top == 0 and 89 <= right <= 91 and bottom == 60
    assert view.geometry["cropped"]
    assert len(bridge.controller.photo_edit._undo) == 1
    assert child(page, "photoCropRect").property("visible")
    assert child(page, "photoCropLeft").property("value") == left
    assert child(page, "photoCropRight").property("value") == right
    assert child(page, "photoClearCrop").property("enabled")
    view.undo()
    assert bridge.controller.photo_edit.recipe is initial
    assert warnings == []


def test_clicks_and_too_small_drags_are_ignored_and_eyes_stay_unselected(
    make_bridge, open_window, out
):
    bridge, view, window, page, warnings = editor_page(make_bridge, open_window, out)
    enter_mode(page)
    initial, selected = bridge.controller.photo_edit.recipe, view.selectedId
    QTest.mouseClick(window, Qt.MouseButton.LeftButton, pos=canvas_point(page, 0.5, 0.5))
    drag(window, canvas_point(page, 0.5, 0.5), canvas_point(page, 0.55, 0.95))
    assert bridge.controller.photo_edit.recipe is initial
    assert view.selectedId == selected and not view.error
    assert warnings == []


def test_a_sub_minimum_drag_shows_a_hint_until_the_next_valid_edit(make_bridge, open_window, out):
    _bridge, view, window, page, warnings = editor_page(make_bridge, open_window, out)
    enter_mode(page)
    hint = child(page, "photoCropHint")
    assert not hint.property("visible")
    drag(window, canvas_point(page, 0.5, 0.5), canvas_point(page, 0.55, 0.95))
    assert hint.property("visible") and hint.property("text")
    assert not view.error and not view.geometry["cropped"]
    drag(window, canvas_point(page, 0.1, 0.0), canvas_point(page, 0.9, 1.0))
    assert view.geometry["cropped"] and not hint.property("visible")
    drag(window, canvas_point(page, 0.5, 0.5), canvas_point(page, 0.55, 0.95))
    assert hint.property("visible")
    click(child(page, "photoRotateRight"))
    assert not hint.property("visible")
    assert warnings == []


@pytest.mark.parametrize("name", ["sourceWidth", "sourceHeight"])
def test_an_unusable_canvas_gives_no_too_small_hint(make_bridge, open_window, out, name):
    _bridge, view, window, page, warnings = editor_page(make_bridge, open_window, out)
    enter_mode(page)
    start, end = canvas_point(page, 0.1, 0.0), canvas_point(page, 0.9, 1.0)
    canvas = child(page, "photoEditCanvas")
    canvas.setProperty(name, 0)  # as if the source size were not known yet
    drag(window, start, end)
    assert not child(page, "photoCropHint").property("visible")
    assert not view.geometry["cropped"] and not view.error
    assert warnings == []


def test_the_hint_does_not_survive_leaving_and_reentering_the_mode(make_bridge, open_window, out):
    _bridge, _view, window, page, warnings = editor_page(make_bridge, open_window, out)
    enter_mode(page)
    hint = child(page, "photoCropHint")
    drag(window, canvas_point(page, 0.5, 0.5), canvas_point(page, 0.55, 0.95))
    assert hint.property("visible")
    enter_mode(page)
    enter_mode(page)
    assert not hint.property("visible")
    assert warnings == []


def test_a_plain_click_gives_no_hint(make_bridge, open_window, out):
    _bridge, _view, window, page, warnings = editor_page(make_bridge, open_window, out)
    enter_mode(page)
    QTest.mouseClick(window, Qt.MouseButton.LeftButton, pos=canvas_point(page, 0.5, 0.5))
    settle()
    assert not child(page, "photoCropHint").property("visible")
    assert warnings == []


def test_dragging_past_the_image_edge_clamps_to_the_source(make_bridge, open_window, out):
    _bridge, view, window, page, warnings = editor_page(make_bridge, open_window, out)
    enter_mode(page)
    drag(window, canvas_point(page, 0.1, -0.2), canvas_point(page, 1.6, 1.8))
    left, top, right, bottom = view.geometry["crop"]
    assert 9 <= left <= 11 and top == 0 and right == 100 and bottom == 60
    assert view.geometry["cropped"] and not view.error
    assert warnings == []


def test_dragging_while_zoomed_maps_through_the_zoom(make_bridge, open_window, out):
    _bridge, view, window, page, warnings = editor_page(make_bridge, open_window, out)
    enter_mode(page)
    child(page, "photoEditCanvas").setProperty("viewZoom", 2)
    settle()
    # Zoom 2 halves the span: canvas fractions 0.1..0.9 are image fractions 0.3..0.7.
    drag(window, canvas_point(page, 0.1, 0.1), canvas_point(page, 0.9, 0.9))
    left, top, right, bottom = view.geometry["crop"]
    assert 28 <= left <= 31 and 17 <= top <= 19 and 69 <= right <= 72 and 41 <= bottom <= 43
    assert warnings == []


def test_crop_drag_is_ignored_outside_the_mode(make_bridge, open_window, out):
    bridge, _view, window, page, warnings = editor_page(make_bridge, open_window, out)
    initial = bridge.controller.photo_edit.recipe
    drag(window, canvas_point(page, 0.1, 0.0), canvas_point(page, 0.9, 1.0))
    assert bridge.controller.photo_edit.recipe is initial
    assert not child(page, "photoCropRect").property("visible")
    assert warnings == []


def test_spin_boxes_clear_reset_and_page_reset(make_bridge, open_window, out):
    bridge, view, window, page, warnings = editor_page(make_bridge, open_window, out)
    enter_mode(page)
    side = bridge.controller.photo_edit
    view.setCrop(10, 0, 90, 60)
    assert child(page, "photoCropTop").property("value") == 0
    assert child(page, "photoCropBottom").property("value") == 60
    invoke(child(page, "photoCropLeft"), "forceActiveFocus")
    QTest.keyClick(window, Qt.Key.Key_Up)
    settle()
    assert view.geometry["crop"] == [11, 0, 90, 60]
    click(child(page, "photoClearCrop"))
    assert not view.geometry["cropped"]
    view.setCrop(10, 0, 90, 60)
    click(child(page, "photoResetGeometry"))
    assert view.geometryNeutral
    assert not child(page, "photoResetGeometry").property("enabled")
    view.reset()
    assert side.recipe is side._initial and view.geometryNeutral
    assert warnings == []


def test_show_result_switch_swaps_the_canvas_image_and_turns_off_on_leaving(
    make_bridge, open_window, out
):
    _bridge, view, _window, page, warnings = editor_page(make_bridge, open_window, out)
    canvas = child(page, "photoEditCanvas")
    assert canvas.property("imageUrl") == view.afterUrl
    enter_mode(page)
    assert canvas.property("cropMode") is True and canvas.property("showEyes") is False
    assert canvas.property("imageUrl") == view.workingUrl
    result = child(page, "photoGeometryResult")
    assert result.property("text") == "Show result" and not result.property("checked")
    result.setProperty("checked", True)
    settle()
    assert canvas.property("imageUrl") == view.afterUrl
    assert canvas.property("cropMode") is False and canvas.property("showEyes") is False
    child(page, "photoBeforeAfter").setProperty("checked", False)
    settle()
    assert canvas.property("imageUrl") == view.beforeUrl
    child(page, "photoBeforeAfter").setProperty("checked", True)
    enter_mode(page)
    assert not result.property("checked")
    assert canvas.property("showEyes") is True and canvas.property("cropMode") is False
    assert warnings == []


def test_geometry_note_appears_only_outside_the_mode_for_non_neutral_geometry(
    make_bridge, open_window, out
):
    _bridge, view, _window, page, warnings = editor_page(make_bridge, open_window, out)
    note = child(page, "photoGeometryNote")
    assert not note.property("visible")
    enter_mode(page)
    view.rotateClockwise()
    assert not note.property("visible")
    enter_mode(page)
    assert note.property("visible")
    assert "whole original" in note.property("text")
    assert "Show result" in note.property("text")
    assert warnings == []
