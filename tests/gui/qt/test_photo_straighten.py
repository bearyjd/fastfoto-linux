"""Straighten properties, slots and the real QML slider, box, reset and canvas states."""

from dataclasses import replace

import pytest
from PIL import Image

from tests.gui.qt import require_qt

require_qt()

from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from fastfoto_linux.gui.photoeditjobs import PhotoEditResult
from fastfoto_linux.photo_edits import frame_size
from tests.gui.photoedit_helpers import preview
from tests.gui.qt import test_qml
from tests.gui.qt.qt_helpers import child, click, invoke, settle
from tests.gui.qt.test_photo_edit_view import open_editor
from tests.gui.qt.test_photo_geometry import canvas_point, drag, editor_page, enter_mode

open_window = test_qml.open_window
pytestmark = pytest.mark.usefixtures("kirigami")
NON_SQUARE = "Straighten needs equal horizontal and vertical resolution."
CLEARS = "Changing the angle clears the crop."


def land(bridge, out, *, straightened=True):
    """Deliver the preview for the latest request; the straightened file has the frame's size."""
    side = bridge.controller.photo_edit
    request = bridge.controller._worker.requests[-1]
    shown = preview(side.recipe, request.generation, out)
    if straightened:
        size = frame_size(side.recipe.source, side.recipe.geometry)
        path = out / f"straightened-{request.generation}.png"
        Image.new("RGB", size, (90, 90, 90)).save(path)
        shown = replace(shown, straightened=path)
    bridge.controller._worker.busy = False
    bridge.controller.on_photo_edit_result(
        PhotoEditResult("preview", request.generation, side.recipe, shown)
    )
    bridge.photoEdit.refresh()
    settle()


def straighten_page(make_bridge, open_window, out, **kwargs):
    bridge, view, window, page, warnings = editor_page(make_bridge, open_window, out, **kwargs)
    enter_mode(page)
    return bridge, view, window, page, warnings


def test_view_exposes_the_straighten_contract(make_bridge, out):
    _bridge, view, _worker = open_editor(make_bridge, out, dpi=100)
    meta = view.metaObject()
    names = {meta.property(i).name() for i in range(meta.propertyCount())}
    assert {
        "frameWidth",
        "frameHeight",
        "canStraighten",
        "straightenedUrl",
        "previewCurrent",
    } <= names
    assert meta.indexOfSlot("setStraighten(int)") >= 0
    assert meta.indexOfSlot("resetStraighten()") >= 0
    assert (view.frameWidth, view.frameHeight) == (100, 60)
    assert view.canStraighten and view.previewCurrent
    assert view.geometry == {
        "quarterTurns": 0,
        "cropped": False,
        "crop": [0, 0, 100, 60],
        "straightenTenths": 0,
    }
    assert view.straightenedUrl == view.workingUrl


def test_straightening_moves_the_frame_and_the_full_crop_and_clamps_the_minimum(make_bridge, out):
    bridge, view, _worker = open_editor(make_bridge, out, dpi=100)
    view.setGeometryMode(True)
    view.setStraighten(30)
    recipe = bridge.controller.photo_edit.recipe
    fw, fh = frame_size(recipe.source, recipe.geometry)
    assert (fw, fh) < (100, 60)
    assert (view.frameWidth, view.frameHeight) == (fw, fh)
    assert view.geometry["straightenTenths"] == 30
    assert view.geometry["crop"] == [0, 0, fw, fh] and not view.geometry["cropped"]
    assert not view.previewCurrent
    assert view.minCropWidth == min(20, fw) and view.minCropHeight == min(20, fh)
    assert (view.outputWidth, view.outputHeight) == (fw, fh)


def test_straightened_url_is_the_preview_image_else_the_working_one(make_bridge, out):
    bridge, view, _worker = open_editor(make_bridge, out, dpi=100)
    view.setGeometryMode(True)
    view.setStraighten(30)
    land(bridge, out, straightened=False)
    assert view.previewCurrent and view.straightenedUrl == view.workingUrl
    view.setStraighten(31)
    land(bridge, out, straightened=True)
    assert view.straightenedUrl.endswith(".png") and "straightened-" in view.straightenedUrl
    assert view.straightenedUrl != view.workingUrl


def test_slots_are_one_entry_each_and_report_domain_errors(make_bridge, out):
    bridge, view, _worker = open_editor(make_bridge, out, dpi=100)
    side = bridge.controller.photo_edit
    view.setStraighten(30)
    assert view.error and side.recipe.geometry.straighten_tenths == 0
    view.setGeometryMode(True)
    view.setStraighten(151)
    assert view.error and side.recipe.geometry.straighten_tenths == 0 and not view.canUndo
    view.setStraighten(30)
    assert not view.error and view.canUndo
    view.resetStraighten()
    assert side.recipe.geometry.straighten_tenths == 0
    view.undo()
    view.undo()
    assert not view.canUndo


def test_non_square_pixels_are_refused_with_a_user_message(make_bridge, out):
    bridge, view, _worker = open_editor(make_bridge, out, dpi=100)
    side = bridge.controller.photo_edit
    side.recipe = replace(
        side.recipe, source=replace(side.recipe.source, dpi_y=200.0, effective_dpi=200.0)
    )
    assert not view.canStraighten
    view.setGeometryMode(True)
    view.setStraighten(30)
    assert "square pixels" in view.error
    assert side.recipe.geometry.straighten_tenths == 0


def test_controls_exist_with_the_contract_ranges_and_hint(make_bridge, open_window, out):
    _bridge, view, _window, page, warnings = straighten_page(make_bridge, open_window, out)
    slider = child(page, "photoStraightenSlider")
    box = child(page, "photoStraightenAngle")
    for control in (slider, box):
        assert (control.property("from"), control.property("to")) == (-150, 150)
        assert control.property("value") == 0 and control.property("enabled")
    assert slider.property("stepSize") == 1
    assert box.property("editable") and not box.property("live")
    assert child(page, "photoStraightenHint").property("text") == CLEARS
    assert not child(page, "photoResetStraighten").property("enabled")
    assert child(page, "photoResetStraighten").property("text") == "Reset straighten"
    assert view.geometry["straightenTenths"] == 0
    assert warnings == []


def test_the_controls_are_only_shown_in_the_mode(make_bridge, open_window, out):
    _bridge, _view, _window, page, warnings = editor_page(make_bridge, open_window, out)
    for name in ("photoStraightenSlider", "photoStraightenAngle", "photoResetStraighten"):
        assert child(page, name).property("visible") is False
    enter_mode(page)
    assert child(page, "photoStraightenSlider").property("visible") is True
    assert warnings == []


def test_the_box_shows_signed_degrees(make_bridge, open_window, out):
    _bridge, view, _window, page, warnings = straighten_page(make_bridge, open_window, out)
    view.setStraighten(-23)
    settle()
    box = child(page, "photoStraightenAngle")
    assert box.property("value") == -23
    assert box.property("contentItem").property("text") == "-2.3 °"
    assert child(page, "photoStraightenSlider").property("value") == -23
    assert child(page, "photoResetStraighten").property("enabled")
    assert warnings == []


def test_slider_drag_is_one_undo_entry_that_restores_angle_and_crop(make_bridge, open_window, out):
    bridge, view, window, page, warnings = straighten_page(make_bridge, open_window, out)
    side = bridge.controller.photo_edit
    view.setCrop(10, 0, 90, 60)
    cropped = side.recipe
    depth = len(side._undo)
    slider = child(page, "photoStraightenSlider")
    start = slider.mapToScene(QPointF(slider.width() * 0.4, slider.height() / 2)).toPoint()
    end = slider.mapToScene(QPointF(slider.width() * 0.8, slider.height() / 2)).toPoint()
    QTest.mousePress(window, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(window, (start + end) / 2, delay=20)
    QTest.mouseMove(window, end, delay=20)
    QTest.mouseRelease(window, Qt.MouseButton.LeftButton, pos=end)
    settle()
    assert view.geometry["straightenTenths"] > 0 and not view.geometry["cropped"]
    assert len(side._undo) == depth + 1
    view.undo()
    assert side.recipe is cropped
    assert child(page, "photoStraightenSlider").property("value") == 0
    assert warnings == []


def test_typing_in_the_box_commits_once_on_enter(make_bridge, open_window, out):
    bridge, view, window, page, warnings = straighten_page(make_bridge, open_window, out)
    side = bridge.controller.photo_edit
    initial = side.recipe
    field = child(page, "photoStraightenAngle").property("contentItem")
    invoke(field, "forceActiveFocus")
    settle()
    QTest.keyClick(window, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    for character in "-2.3":
        QTest.keyClick(window, Qt.Key(ord(character)))
    assert side.recipe is initial, "typing must not commit a partial angle"
    QTest.keyClick(window, Qt.Key.Key_Return)
    settle()
    assert view.geometry["straightenTenths"] == -23 and len(side._undo) == 1
    view.undo()
    assert side.recipe is initial
    assert warnings == []


def test_typing_past_the_limit_is_clamped_to_the_range(make_bridge, open_window, out):
    _bridge, view, window, page, warnings = straighten_page(make_bridge, open_window, out)
    field = child(page, "photoStraightenAngle").property("contentItem")
    invoke(field, "forceActiveFocus")
    settle()
    QTest.keyClick(window, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    for character in "99":
        QTest.keyClick(window, Qt.Key(ord(character)))
    QTest.keyClick(window, Qt.Key.Key_Return)
    settle()
    assert view.geometry["straightenTenths"] == 150 and not view.error
    assert warnings == []


def test_reset_straighten_button_is_one_undo(make_bridge, open_window, out):
    bridge, view, _window, page, warnings = straighten_page(make_bridge, open_window, out)
    side = bridge.controller.photo_edit
    reset = child(page, "photoResetStraighten")
    view.setStraighten(40)
    settle()
    assert reset.property("enabled")
    adjusted = side.recipe
    click(reset)
    assert view.geometry["straightenTenths"] == 0 and not reset.property("enabled")
    view.undo()
    assert side.recipe is adjusted
    assert warnings == []


def test_without_square_pixels_the_controls_are_disabled_and_say_why(make_bridge, open_window, out):
    bridge, view, _window, page, warnings = straighten_page(make_bridge, open_window, out)
    side = bridge.controller.photo_edit
    side.recipe = replace(
        side.recipe, source=replace(side.recipe.source, dpi_y=200.0, effective_dpi=200.0)
    )
    view.refresh()
    settle()
    assert not child(page, "photoStraightenSlider").property("enabled")
    assert not child(page, "photoStraightenAngle").property("enabled")
    assert child(page, "photoStraightenHint").property("text") == NON_SQUARE
    assert warnings == []


def test_with_an_angle_the_canvas_shows_the_straightened_frame(make_bridge, open_window, out):
    bridge, view, _window, page, warnings = straighten_page(make_bridge, open_window, out)
    canvas = child(page, "photoEditCanvas")
    view.setStraighten(30)
    land(bridge, out)
    fw, fh = view.frameWidth, view.frameHeight
    assert canvas.property("imageUrl") == view.straightenedUrl != view.workingUrl
    assert (canvas.property("sourceWidth"), canvas.property("sourceHeight")) == (fw, fh)
    assert canvas.property("cropMode") is True and canvas.property("showEyes") is False
    assert (
        child(page, "photoCropRight").property("to"),
        child(page, "photoCropBottom").property("to"),
    ) == (fw, fh)
    assert warnings == []


def test_a_crop_drag_emits_frame_coordinates(make_bridge, open_window, out):
    _bridge, view, window, page, warnings = straighten_page(make_bridge, open_window, out)
    view.setStraighten(30)
    land(_bridge, out)
    fw, fh = view.frameWidth, view.frameHeight
    drag(window, canvas_point(page, 0.1, 0.0), canvas_point(page, 0.9, 1.0))
    left, top, right, bottom = view.geometry["crop"]
    assert abs(left - 0.1 * fw) <= 2 and top == 0 and abs(right - 0.9 * fw) <= 2 and bottom == fh
    assert view.geometry["cropped"]
    assert warnings == []


def test_crop_mode_waits_for_the_current_preview_when_angled(make_bridge, open_window, out):
    bridge, view, window, page, warnings = straighten_page(make_bridge, open_window, out)
    canvas = child(page, "photoEditCanvas")
    view.setStraighten(30)
    settle()
    assert not view.previewCurrent
    assert canvas.property("cropMode") is False
    stale = bridge.controller.photo_edit.recipe
    drag(window, canvas_point(page, 0.1, 0.0), canvas_point(page, 0.9, 1.0))
    assert bridge.controller.photo_edit.recipe is stale
    land(bridge, out)
    assert canvas.property("cropMode") is True
    assert warnings == []


def test_angle_zero_keeps_the_pr1_canvas_states(make_bridge, open_window, out):
    _bridge, view, _window, page, warnings = straighten_page(make_bridge, open_window, out)
    canvas = child(page, "photoEditCanvas")
    assert canvas.property("imageUrl") == view.workingUrl
    assert (canvas.property("sourceWidth"), canvas.property("sourceHeight")) == (100, 60)
    assert canvas.property("cropMode") is True
    assert warnings == []


def test_show_result_uses_the_after_image_with_an_angle(make_bridge, open_window, out):
    bridge, view, _window, page, warnings = straighten_page(make_bridge, open_window, out)
    canvas = child(page, "photoEditCanvas")
    view.setStraighten(30)
    land(bridge, out)
    child(page, "photoGeometryResult").setProperty("checked", True)
    settle()
    assert canvas.property("imageUrl") == view.afterUrl
    assert canvas.property("cropMode") is False
    assert warnings == []


def test_eye_actions_stay_refused_with_an_angle(make_bridge, open_window, out):
    bridge, view, _window, _page, warnings = straighten_page(make_bridge, open_window, out)
    view.setStraighten(30)
    recipe = bridge.controller.photo_edit.recipe
    view.setAccepted("left", True)
    assert view.error and bridge.controller.photo_edit.recipe is recipe
    assert warnings == []


def test_slider_keys_step_one_tenth_of_a_degree(make_bridge, open_window, out):
    _bridge, view, window, page, warnings = straighten_page(make_bridge, open_window, out)
    invoke(child(page, "photoStraightenSlider"), "forceActiveFocus")
    settle()
    QTest.keyClick(window, Qt.Key.Key_Right)
    settle()
    assert view.geometry["straightenTenths"] == 1
    assert child(page, "photoStraightenAngle").property("value") == 1
    assert warnings == []
