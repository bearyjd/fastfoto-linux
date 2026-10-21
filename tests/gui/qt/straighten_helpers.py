"""Shared helpers for the straighten GUI tests."""

from dataclasses import replace

from PIL import Image

from tests.gui.qt import require_qt

require_qt()

from fastfoto_linux.gui.photoeditjobs import PhotoEditResult
from fastfoto_linux.photo_edits import frame_size
from tests.gui.photoedit_helpers import preview
from tests.gui.qt.qt_helpers import settle
from tests.gui.qt.test_photo_geometry import editor_page, enter_mode


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


def save_landed(bridge):
    side = bridge.controller.photo_edit
    bridge.controller._worker.busy = False
    bridge.photoEdit.save()
    request = bridge.controller._worker.requests[-1]
    bridge.controller._worker.busy = False
    bridge.controller.on_photo_edit_result(PhotoEditResult("save", request.generation, side.recipe))
    bridge.photoEdit.refresh()
    settle()
