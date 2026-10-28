"""Crop shapes in the real photo editor: the view child, the controls, keys and ratio drags."""

import math
from pathlib import Path

import numpy as np
import pytest

from tests.gui.qt import require_qt

require_qt()

from PySide6.QtCore import Q_ARG, QMetaObject, QPointF, Qt
from PySide6.QtQml import QQmlEngine, QQmlExpression
from PySide6.QtTest import QTest

from fastfoto_linux.gui.photoeditaspect import PRESETS, aspect_crop
from fastfoto_linux.gui.photoeditcoords import source_crop
from fastfoto_linux.gui.photoeditjobs import PhotoEditResult
from tests.gui.photoedit_helpers import preview
from tests.gui.qt import test_qml
from tests.gui.qt.qt_helpers import child, invoke, settle
from tests.gui.qt.test_photo_edit_view import open_editor
from tests.gui.qt.test_photo_geometry import canvas_point, editor_page, enter_mode
from tests.gui.qt.test_photo_tone import ready_page

open_window = test_qml.open_window
pytestmark = pytest.mark.usefixtures("kirigami")
QML = Path(__file__).resolve().parents[3] / "src/fastfoto_linux/gui/qml"
TOO_SMALL = "This photo is too small for that crop shape at the 5 mm minimum."


def activate(combo, index):
    assert QMetaObject.invokeMethod(combo, "activated", Q_ARG(int, index))
    settle()


def index_of(preset_id):
    return [p.id for p in PRESETS].index(preset_id)


def js(item, script):
    expression = QQmlExpression(QQmlEngine.contextForObject(item), item, script)
    value, _undefined = expression.evaluate()
    assert not expression.hasError(), expression.error()
    return value.toVariant() if hasattr(value, "toVariant") else value


def test_the_aspect_child_exposes_the_contract(make_bridge, out):
    _bridge, view, _worker = open_editor(make_bridge, out, dpi=100)
    meta = view.aspect.metaObject()
    names = {meta.property(i).name() for i in range(meta.propertyCount())}
    assert {"preset", "portrait", "ratio", "canSwap", "shapeText"} <= names
    for slot in ("setPreset(QString)", "swap()", "setAspectCrop(int,int,int,int)"):
        assert meta.indexOfSlot(slot) >= 0, slot
    aspect = view.aspect
    assert (aspect.preset, aspect.portrait, aspect.ratio) == ("free", False, [])
    assert (aspect.canSwap, aspect.shapeText) == (False, "")


def test_the_slots_drive_the_lock_and_the_texts_follow(make_bridge, out):
    _bridge, view, _worker = open_editor(make_bridge, out, dpi=100)
    seen = []
    view.aspect.changed.connect(lambda: seen.append(1))
    view.setGeometryMode(True)
    view.aspect.setPreset("4:3")
    assert seen and view.geometry["crop"] == [10, 0, 90, 60]
    assert (view.aspect.ratio, view.aspect.shapeText) == ([4, 3], "4:3 landscape")
    assert view.aspect.canSwap is True
    view.aspect.swap()
    assert (view.aspect.portrait, view.aspect.shapeText) == (True, "3:4 portrait")
    view.aspect.setPreset("1:1")
    assert view.aspect.shapeText == "1:1" and view.aspect.canSwap is False
    view.aspect.setPreset("original")
    assert view.aspect.shapeText == "Original, landscape"
    view.setCrop(10, 0, 89, 60)
    assert (view.aspect.preset, view.aspect.ratio, view.aspect.shapeText) == ("free", [], "")
    view.aspect.setPreset("4:3")
    view.aspect.setAspectCrop(10, 10, 60, 40)
    assert view.geometry["crop"] == [15, 10, 55, 40]


def test_a_refused_choice_is_reported_and_the_preset_stays(make_bridge, out):
    _bridge, view, _worker = open_editor(make_bridge, out, dpi=300)
    view.aspect.setPreset("4:3")
    assert view.error and view.aspect.preset == "free"
    view.setGeometryMode(True)
    view.aspect.setPreset("4:3")
    view.aspect.setPreset("16:9")
    assert view.error == TOO_SMALL and view.aspect.preset == "4:3"


def test_the_controls_are_named_and_only_shown_in_the_mode(make_bridge, open_window, out):
    _bridge, _view, _window, page, warnings = editor_page(make_bridge, open_window, out)
    names = ("photoCropAspect", "photoCropAspectSwap")
    assert not any(child(page, name).property("visible") for name in names)
    enter_mode(page)
    assert all(child(page, name).property("visible") for name in names)
    assert child(page, "photoCropAspectSwap").property("text") == "Swap orientation"
    assert child(page, "photoCropAspect").property("activeFocusOnTab")
    text = (QML / "PhotoGeometryControls.qml").read_text(encoding="utf-8")
    for name, label in (
        ("photoCropAspect", "Crop shape"),
        ("photoCropAspectSwap", "Swap orientation"),
    ):
        block = text[text.index(f'objectName: "{name}"') :].split("\n    }")[0]
        assert f'Accessible.name: qsTr("{label}")' in block
    assert warnings == []


def test_the_combo_lists_the_presets_in_order_and_each_choice_calls_the_slot(
    make_bridge, open_window, out
):
    _bridge, view, _window, page, warnings = editor_page(make_bridge, open_window, out)
    enter_mode(page)
    combo = child(page, "photoCropAspect")
    assert list(combo.property("model")) == [p.label for p in PRESETS]
    for preset in PRESETS[1:]:
        activate(combo, index_of(preset.id))
        assert view.aspect.preset == preset.id
    activate(combo, 0)
    assert view.aspect.preset == "free"
    assert warnings == []


def test_a_refused_choice_and_a_dropped_lock_show_truthfully_in_the_combo(
    make_bridge, open_window, out
):
    bridge, view, _worker = open_editor(make_bridge, out, dpi=300)
    window, warnings = open_window(bridge)
    page = ready_page(window)
    enter_mode(page)
    combo = child(page, "photoCropAspect")
    # A user pick sets currentIndex (dropping its binding) and then fires `activated`.
    for pick in ("4:3", "16:9"):
        js(
            combo, f"currentIndex = {index_of(pick)}"
        )  # a JS write drops the binding, as a pick does
        activate(combo, index_of(pick))
    assert view.aspect.preset == "4:3" and combo.property("currentIndex") == index_of("4:3")
    view.setCrop(10, 0, 89, 60)
    settle()
    assert combo.property("currentIndex") == 0
    assert warnings == []


def test_keyboard_only_choose_a_shape_and_swap_it(make_bridge, open_window, out):
    _bridge, view, window, page, warnings = editor_page(make_bridge, open_window, out)
    enter_mode(page)
    # The popup does not take keys offscreen, so use the closed box: each Down fires `activated`,
    # and every step re-fits inside the previous fit (the documented binding rule, R7).
    invoke(child(page, "photoCropAspect"), "forceActiveFocus")
    for _ in range(index_of("4:3")):
        QTest.keyClick(window, Qt.Key.Key_Down)
        settle()
    assert view.aspect.preset == "4:3" and view.geometry["crop"] == [20, 7, 80, 52]
    view.setCrop(20, 10, 60, 40)
    view.aspect.setPreset("4:3")
    invoke(child(page, "photoCropAspectSwap"), "forceActiveFocus")
    QTest.keyClick(window, Qt.Key.Key_Space)
    settle()
    assert view.aspect.portrait is True and view.geometry["crop"] == [25, 5, 55, 45]
    assert warnings == []


def test_swap_is_enabled_only_for_a_non_square_shape(make_bridge, open_window, out):
    _bridge, view, _window, page, warnings = editor_page(make_bridge, open_window, out)
    enter_mode(page)
    swap = child(page, "photoCropAspectSwap")
    assert not swap.property("enabled")
    view.aspect.setPreset("1:1")
    assert not swap.property("enabled")
    view.aspect.setPreset("3:2")
    assert swap.property("enabled")
    assert warnings == []


def test_the_shape_label_and_the_odd_turn_hint(make_bridge, open_window, out):
    _bridge, view, _window, page, warnings = editor_page(make_bridge, open_window, out)
    enter_mode(page)
    label, hint = child(page, "photoCropAspectShape"), child(page, "photoCropAspectTurned")
    assert not label.property("visible") and not hint.property("visible")
    view.aspect.setPreset("4:3")
    assert label.property("visible") and label.property("text") == "Saved shape 4:3 landscape"
    assert not hint.property("visible")
    view.rotateClockwise()
    assert hint.property("visible") and "Show result" in hint.property("text")
    assert label.property("text") == "Saved shape 3:4 portrait"
    view.setCrop(10, 0, 89, 60)
    assert not label.property("visible") and not hint.property("visible")
    assert warnings == []


def mapped(picture, x, y):
    return js(
        picture,
        f"(function() {{ const p = mapFromItem(parent, {x!r}, {y!r}); return [p.x, p.y]; }})()",
    )


def python_box(picture, points, ratio, source):
    (x0, y0), (x1, y1) = (mapped(picture, *p) for p in points)
    return aspect_crop(
        x0, y0, x1, y1, ratio=tuple(ratio), min_width=1, min_height=1,
        source_width=source[0], source_height=source[1],
        painted_width=picture.property("paintedWidth"),
        painted_height=picture.property("paintedHeight"),
        item_width=picture.width(), item_height=picture.height(),
    )  # fmt: skip


def test_a_ratio_drag_shows_the_band_and_stores_the_python_box(make_bridge, open_window, out):
    bridge, view, window, page, warnings = editor_page(make_bridge, open_window, out)
    enter_mode(page)
    view.aspect.setPreset("4:3")
    canvas, picture = child(page, "photoEditCanvas"), child(page, "photoCanvasImage")
    start, end = canvas_point(page, 0.1, 0.1), canvas_point(page, 0.5, 0.4)
    band = child(page, "photoAspectBand")
    QTest.mousePress(window, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(window, end, delay=20)
    settle()
    assert band.property("visible") and abs(band.width() / band.height() - 4 / 3) < 0.1
    QTest.mouseRelease(window, Qt.MouseButton.LeftButton, pos=end)
    settle()
    assert not band.property("visible")
    points = [tuple(canvas.mapFromScene(QPointF(p)).toTuple()) for p in (start, end)]
    want = python_box(picture, points, view.aspect.ratio, (100, 60))
    assert want is not None and view.geometry["crop"] == list(want)
    assert (
        view.aspect.preset == "4:3" and len(bridge.controller.photo_edit._undo) == 2
    )  # the choice, then the drag
    assert warnings == []


def parity_cases():
    rng = np.random.default_rng(5)
    ratios = [[4, 3], [3, 4], [16, 9], [9, 16], [3, 2], [2, 3], [7, 5], [5, 7], [1, 1], [5, 3]]
    sizes = [(100, 60), (1000, 600), (3000, 2000), (4000, 2667), (2667, 4000)]
    cases = [
        (ratios[i % 10], sizes[i % 5], 1 + i % 2, rng.uniform(-0.1, 1.1, size=4).round(4).tolist())
        for i in range(48)
    ]
    for corners in ((0.2, 0.2, 0.8, 0.5), (0.8, 0.5, 0.2, 0.2), (0.2, 0.5, 0.8, 0.2)):
        cases.append(([4, 3], (1000, 600), 1, list(corners)))
    for ratio in ratios:  # the whole frame, both ways: where the two rounding forms matter
        cases += [(ratio, size, 1, [0, 0, 1, 1]) for size in [*sizes, (59, 78), (7, 3)]]
        cases += [(ratio, size, 1, [1, 1, 0, 0]) for size in [*sizes, (59, 78), (7, 3)]]
    return cases


@pytest.mark.parametrize("ratio", [[4, 3], [3, 4], [16, 9], [7, 5], [1, 1]])
def test_the_canvas_drag_equals_the_python_drag_over_a_table(make_bridge, open_window, out, ratio):
    _bridge, _view, _window, page, warnings = editor_page(make_bridge, open_window, out)
    enter_mode(page)
    canvas, picture = child(page, "photoEditCanvas"), child(page, "photoCanvasImage")
    compared = 0
    for r, source, zoom, (a, b, c, d) in parity_cases():
        if r != ratio:
            continue
        canvas.setProperty("viewZoom", zoom)
        canvas.setProperty("sourceWidth", source[0])
        canvas.setProperty("sourceHeight", source[1])
        canvas.setProperty("cropRatio", ratio)
        w, h = canvas.width(), canvas.height()
        points = [(a * w, b * h), (c * w, d * h)]
        want = python_box(picture, points, ratio, source)
        got = js(
            canvas,
            f"aspectCrop({points[0][0]!r}, {points[0][1]!r}, {points[1][0]!r}, {points[1][1]!r})",
        )
        if want is not None:
            assert got == list(want), (ratio, source, zoom, points)
            compared += 1
    assert compared >= 3
    assert warnings == []


def finish_preview(bridge, view, worker, out):
    request = worker.requests[-1]
    worker.busy = False
    recipe = bridge.controller.photo_edit.recipe
    shown = preview(recipe, request.generation, out)
    bridge.controller.on_photo_edit_result(
        PhotoEditResult("preview", request.generation, recipe, shown)
    )
    view.refresh()


@pytest.mark.parametrize("again", ["4:3", "free"])
def test_a_refusal_does_not_keep_save_disabled_after_a_good_choice(make_bridge, out, again):
    bridge, view, worker = open_editor(make_bridge, out, dpi=300)
    view.setGeometryMode(True)
    view.aspect.setPreset("4:3")
    finish_preview(bridge, view, worker, out)
    view.aspect.setPreset("16:9")
    assert view.error == TOO_SMALL and not view.canSave
    view.aspect.setPreset(again)
    assert view.error == ""
    finish_preview(bridge, view, worker, out)
    assert view.canSave


def test_a_canvas_click_without_movement_makes_no_box(make_bridge, open_window, out):
    _bridge, _view, _window, page, warnings = editor_page(make_bridge, open_window, out)
    enter_mode(page)
    canvas = child(page, "photoEditCanvas")
    canvas.setProperty("sourceWidth", 1000)
    canvas.setProperty("sourceHeight", 600)
    canvas.setProperty("cropRatio", [4, 3])
    for fx, fy in ((0.37, 0.41), (0.5, 0.5), (0.25, 0.75)):
        x, y = fx * canvas.width(), fy * canvas.height()
        assert js(canvas, f"aspectCrop({x!r}, {y!r}, {x!r}, {y!r})") is None
    assert warnings == []


def tie_press(picture, source):
    """A canvas x whose source pixel is a micro-pixel tie: round(v, 6) and half-up disagree."""
    left = (picture.width() - picture.property("paintedWidth")) / 2
    scale = source[0] / picture.property("paintedWidth")
    for k in range(source[0] - 1):
        x = left + (k + 0.9999995) / scale
        for step in range(-6, 7):
            for _ in range(abs(step)):
                x = math.nextafter(x, math.inf if step > 0 else -math.inf)
            v = (mapped(picture, x, 0.0)[0] - left) * source[0] / picture.property("paintedWidth")
            if math.floor(round(v, 6)) != math.floor(math.floor(v * 1e6 + 0.5) / 1e6):
                return x
            x = left + (k + 0.9999995) / scale
    raise AssertionError("no tie press found")


@pytest.mark.parametrize("source", [(100, 60), (1000, 600)])
def test_a_micro_pixel_tie_is_read_the_same_by_the_canvas_and_python(
    make_bridge, open_window, out, source
):
    _bridge, _view, _window, page, warnings = editor_page(make_bridge, open_window, out)
    enter_mode(page)
    canvas, picture = child(page, "photoEditCanvas"), child(page, "photoCanvasImage")
    canvas.setProperty("viewZoom", 1)
    canvas.setProperty("sourceWidth", source[0])
    canvas.setProperty("sourceHeight", source[1])
    canvas.setProperty("cropRatio", [4, 3])
    press = tie_press(picture, source)
    end = (0.9 * canvas.width(), 0.8 * canvas.height())
    points = [(press, 0.2 * canvas.height()), end]
    flat = f"{points[0][0]!r}, {points[0][1]!r}, {points[1][0]!r}, {points[1][1]!r}"
    want = python_box(picture, points, [4, 3], source)
    assert want is not None and js(canvas, f"aspectCrop({flat})") == list(want)
    (x0, y0), (x1, y1) = (mapped(picture, *p) for p in points)
    free = source_crop(
        x0, y0, x1, y1, min_width=1, min_height=1, source_width=source[0],
        source_height=source[1], painted_width=picture.property("paintedWidth"),
        painted_height=picture.property("paintedHeight"), item_width=picture.width(),
        item_height=picture.height(),
    )  # fmt: skip
    assert free is not None and js(canvas, f"sourceCrop({flat})") == list(free)
    assert warnings == []
