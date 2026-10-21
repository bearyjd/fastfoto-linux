"""Straighten preview handling: the held preview, the shown frame and preview retries."""

import pytest

from tests.gui.qt import require_qt

require_qt()

from fastfoto_linux.gui.photoeditjobs import PhotoEditResult
from tests.gui.qt import test_qml
from tests.gui.qt.qt_helpers import child, settle
from tests.gui.qt.straighten_helpers import land, save_landed, straighten_page
from tests.gui.qt.test_photo_edit_view import open_editor

open_window = test_qml.open_window
pytestmark = pytest.mark.usefixtures("kirigami")


def test_until_the_new_preview_lands_the_canvas_holds_the_last_settled_image(
    make_bridge, open_window, out
):
    bridge, view, _window, page, warnings = straighten_page(make_bridge, open_window, out)
    canvas = child(page, "photoEditCanvas")
    child(page, "photoBeforeAfter").setProperty("checked", False)
    settle()
    settled = canvas.property("imageUrl")
    assert settled == view.beforeUrl != view.workingUrl
    view.setStraighten(30)
    settle()
    assert not view.previewCurrent
    # The held preview is still the unangled one, so its working image at the source size.
    assert canvas.property("imageUrl") == view.workingUrl != settled
    assert (canvas.property("sourceWidth"), canvas.property("sourceHeight")) == (100, 60)
    land(bridge, out)
    assert canvas.property("imageUrl") == view.straightenedUrl
    assert canvas.property("sourceWidth") == view.frameWidth
    assert warnings == []


def test_an_angle_to_angle_change_keeps_the_previous_frame_until_the_preview_lands(
    make_bridge, open_window, out
):
    bridge, view, _window, page, warnings = straighten_page(make_bridge, open_window, out)
    canvas = child(page, "photoEditCanvas")
    child(page, "photoBeforeAfter").setProperty("checked", False)
    view.setStraighten(30)
    settle()
    land(bridge, out)
    first = (canvas.property("sourceWidth"), canvas.property("sourceHeight"))
    first_url = canvas.property("imageUrl")
    assert first == (view.frameWidth, view.frameHeight)
    view.setStraighten(40)
    settle()
    assert not view.previewCurrent
    assert (view.frameWidth, view.frameHeight) != first
    assert (canvas.property("sourceWidth"), canvas.property("sourceHeight")) == first
    assert canvas.property("imageUrl") == first_url
    assert not canvas.property("cropMode")
    land(bridge, out)
    assert (canvas.property("sourceWidth"), canvas.property("sourceHeight")) == (
        view.frameWidth,
        view.frameHeight,
    )
    assert warnings == []


def shown(view):
    return (view.shownFrameWidth, view.shownFrameHeight)


def test_the_shown_frame_follows_the_held_preview_not_the_draft(make_bridge, out):
    bridge, view, _worker = open_editor(make_bridge, out, dpi=100)
    assert shown(view) == (100, 60)
    view.setGeometryMode(True)
    view.setStraighten(30)
    assert shown(view) == (100, 60) != (view.frameWidth, view.frameHeight)
    land(bridge, out)
    first = shown(view)
    assert first == (view.frameWidth, view.frameHeight) != (100, 60)
    view.setStraighten(40)
    assert shown(view) == first != (view.frameWidth, view.frameHeight)
    view.undo()
    assert shown(view) == first == (view.frameWidth, view.frameHeight)
    land(bridge, out)
    assert shown(view) == (view.frameWidth, view.frameHeight)


def test_the_shown_frame_survives_a_save_and_resets_on_close(make_bridge, out):
    bridge, view, _worker = open_editor(make_bridge, out, dpi=100)
    view.setGeometryMode(True)
    view.setStraighten(50)
    land(bridge, out)
    angled = shown(view)
    save_landed(bridge)
    assert shown(view) == angled == (view.frameWidth, view.frameHeight)
    view.stop()
    assert shown(view) == (0, 0)


def test_the_shown_frame_is_the_source_when_an_angled_preview_has_no_straightened_file(
    make_bridge, out
):
    bridge, view, _worker = open_editor(make_bridge, out, dpi=100)
    view.setGeometryMode(True)
    view.setStraighten(30)
    land(bridge, out, straightened=False)
    assert view.previewCurrent and view.straightenedUrl == view.workingUrl
    # The image is the unstraightened working one, so its size must be the source size.
    assert (
        shown(view) == (view.sourceWidth, view.sourceHeight) != (view.frameWidth, view.frameHeight)
    )


def fail_latest(bridge, *, cancelled=False):
    side = bridge.controller.photo_edit
    request = bridge.controller._worker.requests[-1]
    bridge.controller._worker.busy = False
    bridge.controller.on_photo_edit_result(
        PhotoEditResult(
            "preview",
            request.generation,
            side.recipe,
            error="" if cancelled else "boom",
            cancelled=cancelled,
        )
    )
    bridge.photoEdit.refresh()


@pytest.mark.parametrize("cancelled", [False, True])
def test_repeating_the_angle_after_a_failed_preview_retries_without_an_undo_entry(
    make_bridge, out, cancelled
):
    bridge, view, worker = open_editor(make_bridge, out, dpi=100)
    side = bridge.controller.photo_edit
    view.setGeometryMode(True)
    view.setStraighten(30)
    fail_latest(bridge, cancelled=cancelled)
    assert not view.previewCurrent
    before = (len(worker.requests), len(side._undo), side.recipe)
    view.setStraighten(30)
    assert len(worker.requests) == before[0] + 1
    assert (len(side._undo), side.recipe) == before[1:]
    land(bridge, out)
    assert view.previewCurrent
    view.setStraighten(30)
    assert len(worker.requests) == before[0] + 1  # current again: a repeat is a no-op


def test_repeating_the_angle_while_a_preview_is_in_flight_does_not_queue_another(make_bridge, out):
    bridge, view, worker = open_editor(make_bridge, out, dpi=100)
    view.setGeometryMode(True)
    view.setStraighten(30)
    count = len(worker.requests)
    view.setStraighten(30)
    assert len(worker.requests) == count
    assert bridge.controller.photo_edit._pending is None
