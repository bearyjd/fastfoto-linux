"""A QML string such as "false" is never taken as the destructive confirmation."""

from tests.gui.qt import require_qt

require_qt()

import pytest
from PySide6.QtQml import QJSEngine

from tests.gui.qt.test_bridge_review import open_review
from tests.gui.qt.test_photo_edit_view import open_editor


def js(view):
    engine = QJSEngine()
    engine.globalObject().setProperty("view", engine.newQObject(view))
    return engine, engine.evaluate


@pytest.mark.parametrize("value", ['"false"', '"x"', "1", "null"])
def test_delete_originals_refuses_anything_but_a_real_bool(make_bridge, out, value):
    bridge, view = open_review(make_bridge, out)
    calls = []
    view._side.delete_originals = calls.append
    _engine, run = js(view)
    run(f"view.deleteOriginals({value})")
    assert calls == []
    assert bridge.controller.banner.kind == "error"


def test_delete_originals_still_passes_a_real_true(make_bridge, out):
    _bridge, view = open_review(make_bridge, out)
    calls = []
    view._side.delete_originals = calls.append
    _engine, run = js(view)
    run("view.deleteOriginals(true)")
    run("view.deleteOriginals(false)")
    assert calls == [True, False]


@pytest.mark.parametrize("value", ['"false"', '"true"', "1", "null"])
def test_photo_close_refuses_anything_but_a_real_bool(make_bridge, out, value):
    _bridge, view, _worker = open_editor(make_bridge, out)
    view.setAccepted("left", True)
    assert view.dirty
    _engine, run = js(view)
    run(f"view.close({value})")
    assert view.active and view.dirty
    assert "not a yes or no answer" in view.error


def test_photo_close_still_accepts_a_real_true(make_bridge, out):
    _bridge, view, _worker = open_editor(make_bridge, out)
    view.setAccepted("left", True)
    _engine, run = js(view)
    run("view.close(true)")
    assert not view.active
