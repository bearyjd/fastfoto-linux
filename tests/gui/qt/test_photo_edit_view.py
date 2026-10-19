"""Public child interface, eligibility and dirty-close protection for photo review."""

from tests.gui.qt import require_qt

require_qt()

from PySide6.QtCore import QUrl

from fastfoto_linux.gui.photoeditjobs import PhotoEditResult
from fastfoto_linux.gui.qt.photos_model import PhotosModel
from fastfoto_linux.gui.state import State
from fastfoto_linux.photo_edits import PhotoEditRecipe
from tests.gui.photoedit_helpers import EditWorker, eyes, preview, source


def open_editor(make_bridge, out, *, candidates=None, dpi=300):
    bridge = make_bridge()
    assert hasattr(bridge, "photoEdit"), "Bridge must expose a dedicated photo editor child"
    src = source(out, dpi=dpi)
    from fastfoto_linux.gui.photos import PhotoItem

    bridge.controller._photos = (PhotoItem(out, 1, src.path, None, None),)
    bridge.controller._state = State.DONE
    worker = EditWorker()
    bridge.controller._worker = worker
    view = bridge.photoEdit
    view.openPhoto(0)
    request = worker.requests[-1]
    recipe = PhotoEditRecipe(src, eyes() if candidates is None else candidates)
    worker.busy = False
    bridge.controller.on_photo_edit_result(
        PhotoEditResult(
            "open", request.generation, recipe, preview(recipe, request.generation, out)
        )
    )
    view.refresh()
    return bridge, view, worker


def test_bridge_child_exposes_full_review_and_source_contract(make_bridge, out):
    bridge, view, _worker = open_editor(make_bridge, out)
    assert bridge.photoEdit is view
    names = {view.metaObject().property(i).name() for i in range(view.metaObject().propertyCount())}
    assert {
        "active",
        "busy",
        "dirty",
        "error",
        "sourceLabel",
        "beforeUrl",
        "afterUrl",
        "roiBeforeUrl",
        "roiAfterUrl",
        "sourceWidth",
        "sourceHeight",
        "candidates",
        "selectedId",
        "canUndo",
        "canSave",
        "savedEditUrl",
    } <= names
    assert "cropped" in view.sourceLabel.lower() and "upright" in view.sourceLabel.lower()
    assert (view.sourceWidth, view.sourceHeight) == (100, 60)
    assert not view.candidates[0]["accepted"]
    assert view.candidates[0]["id"] == "left"
    assert QUrl(view.beforeUrl).isLocalFile()


def test_selection_accept_strength_and_undo_use_eye_ids(make_bridge, out):
    _bridge, view, _worker = open_editor(make_bridge, out)
    view.selectEye("right")
    view.setAccepted("right", True)
    view.beginGesture()
    view.setStrength("right", 80)
    view.setStrength("right", 20)
    view.endGesture()
    assert view.selectedId == "right"
    assert view.candidates[1]["accepted"]
    assert view.candidates[1]["strength"] == 20
    view.undo()
    assert view.candidates[1]["strength"] == 100
    assert view.candidates[1]["accepted"]


def test_window_and_page_close_veto_dirty_review_until_discard_confirmed(make_bridge, out):
    bridge, view, _worker = open_editor(make_bridge, out)
    view.setAccepted("left", True)
    assert not bridge.requestClose()
    assert not view.close()
    assert view.active and view.dirty
    assert view.close(True)
    assert not view.active


def test_results_model_explains_absent_original_and_unprocessed_sheet(out):
    from fastfoto_linux.gui.photos import PhotoItem

    model = PhotosModel()
    roles = {bytes(value).decode(): role for role, value in model.roleNames().items()}
    assert {"canReviewRedEyes", "reviewRedEyesReason"} <= roles.keys()
    model.set_items((PhotoItem(out, 1, None, out / "synthetic_a.jpg", None),))
    idx = model.index(0, 0)
    assert not model.data(idx, roles["canReviewRedEyes"])
    assert "original" in model.data(idx, roles["reviewRedEyesReason"]).lower()
