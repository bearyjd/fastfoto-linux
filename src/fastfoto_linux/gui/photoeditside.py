"""Qt-free photo review lifecycle, immutable decisions and latest-preview scheduling."""

from contextlib import suppress
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from fastfoto_linux.gui.photoeditgeometry import PhotoGeometryActions
from fastfoto_linux.gui.photoeditjobs import PhotoEditRequest, PhotoEditResult, PhotoEditTools
from fastfoto_linux.gui.photos import PhotoItem
from fastfoto_linux.gui.state import ActionBlockedError, Mode
from fastfoto_linux.photo_edits import (
    EyeEdit,
    PhotoEditRecipe,
    PhotoPreview,
    PhotoTone,
    SavedPhotoEdit,
    update_tone,
)

if TYPE_CHECKING:
    from fastfoto_linux.gui.controller import Controller


def eligibility(item: PhotoItem) -> str:
    """Only a retained, processed original is a recoverable editing source."""
    if item.unprocessed:
        return "This sheet was not processed into a photo; red-eye review needs a cropped photo."
    if item.original is None:
        return "The cropped, upright original JPEG was not kept. Keep original for later edits."
    if not item.original.is_file():
        return "The retained original JPEG is missing. Restore it before reviewing red eyes."
    return ""


def _preview_paths(preview: PhotoPreview | None) -> set[Path]:
    if preview is None:
        return set()
    return {
        path
        for path in (
            preview.before,
            preview.after,
            preview.working,
            preview.roi_before,
            preview.roi_after,
            preview.straightened,
        )
        if path is not None
    }


class PhotoEditSide(PhotoGeometryActions):
    def __init__(
        self,
        controller: "Controller",
        *,
        cache_dir: Path,
        tools: PhotoEditTools | None = None,
    ) -> None:
        self._controller, self._cache_dir = controller, cache_dir
        self._tools = tools or PhotoEditTools()
        self.active = False
        self.error = ""
        self.recipe: PhotoEditRecipe | None = None
        self.preview: PhotoPreview | None = None
        self.selected_id = ""
        self.generation = 0
        self.saved_edit: SavedPhotoEdit | None = None
        self._initial: PhotoEditRecipe | None = None
        self._clean: PhotoEditRecipe | None = None
        self._undo: list[PhotoEditRecipe] = []
        self._inflight: PhotoEditRequest | None = None
        self._pending: PhotoEditRequest | None = None
        self._gesture = False
        self._gesture_saved = False
        self._manual_number = 0

    @property
    def busy(self) -> bool:
        return self._inflight is not None

    @property
    def _worker_busy(self) -> bool:
        return bool(getattr(self._controller._worker, "busy", False))

    @property
    def dirty(self) -> bool:
        return self.recipe is not None and self.recipe is not self._clean

    @property
    def can_undo(self) -> bool:
        return bool(self._undo) and self.can_edit

    @property
    def can_reset(self) -> bool:
        return self.can_edit and self.recipe is not self._initial

    @property
    def can_save(self) -> bool:
        return self.can_edit and not self._worker_busy and not self.busy and not self.error

    @property
    def can_edit(self) -> bool:
        return (
            self.active
            and self.recipe is not None
            and (self._inflight is None or self._inflight.operation == "preview")
        )

    def _check_open(self) -> None:
        c = self._controller
        if self._worker_busy or c.busy:
            raise ActionBlockedError("Wait for the running job before opening a photo review.")
        if self.dirty:
            raise ActionBlockedError("Close or discard the current photo edits first.")
        if c.review.active:
            raise ActionBlockedError("Close the document review before opening a photo review.")

    def open_photo(self, row: int) -> None:
        self._check_open()
        if self._controller.mode is not Mode.PHOTOS:
            raise ActionBlockedError("Switch to Photos before reviewing a photo.")
        items = self._controller.photos
        if not 0 <= row < len(items):
            raise ValueError("Choose a photo from the results.")
        item = items[row]
        reason = eligibility(item)
        if reason:
            raise ValueError(reason)
        self._open("open", item.original)

    def open_saved(self, path: Path) -> None:
        self._check_open()
        self._open("reopen", path)

    def _open(self, operation: str, path: Path | None) -> None:
        self._forget_preview()
        self.active = True
        self.recipe = self._initial = self._clean = None
        self.selected_id, self.error = "", ""
        self.saved_edit = None
        self._undo.clear()
        self._pending = None
        self.geometry_mode = False
        self.end_gesture()
        self.generation += 1
        self._submit(PhotoEditRequest(operation, self.generation, path=path))
        self._changed()

    def _submit(self, request: PhotoEditRequest) -> None:
        self._controller._worker.photo_edit_job(request)
        self._inflight = request

    def complete(self, result: PhotoEditResult) -> None:
        current = self._inflight
        if current is None or current.generation != result.generation:
            self._discard_preview(result.preview)
            return
        self._inflight = None
        if not self.active or result.generation != self.generation:
            self._discard_preview(result.preview)
        else:
            self._accept_result(result)
        pending, self._pending = self._pending, None
        if self.active and pending is not None:
            self._submit(pending)
        self._changed()

    def _accept_result(self, result: PhotoEditResult) -> None:
        self.error = result.error or (
            "Photo edit cancelled. Your draft is kept." if result.cancelled else ""
        )
        if result.error or result.cancelled:
            return
        if result.operation in {"open", "reopen"}:
            self.recipe = self._initial = self._clean = result.recipe
            if self.recipe and self.recipe.eyes:
                self.selected_id = self.recipe.eyes[0].id
        if result.preview is not None:
            self._discard_preview(self.preview, keeping=result.preview)
            self.preview = result.preview
        if result.saved is not None:
            self.saved_edit = result.saved
            self._clean = result.saved.recipe

    def _require_edit(self) -> PhotoEditRecipe:
        if not self.can_edit:
            raise ActionBlockedError("Wait for the photo to open or finish saving before editing.")
        assert self.recipe is not None
        return self.recipe

    def _eye(self, eye_id: str) -> EyeEdit:
        recipe = self._require_edit()
        for eye in recipe.eyes:
            if eye.id == eye_id:
                return eye
        raise ValueError("That eye is no longer in this review.")

    def select_eye(self, eye_id: str) -> None:
        self._require_eye_edit()
        self._eye(eye_id)
        if eye_id != self.selected_id:
            self.selected_id = eye_id
            self.request_preview()

    def set_accepted(self, eye_id: str, value: bool) -> None:
        self._require_eye_edit()
        eye = self._eye(eye_id)
        if eye.accepted != value:
            self._replace(eye_id, replace(eye, accepted=value))

    def set_strength(self, eye_id: str, value: int) -> None:
        self._require_eye_edit()
        eye = self._eye(eye_id)
        if eye.strength != value:
            self._replace(eye_id, replace(eye, strength=value))

    def set_tone(self, field: str, value: int) -> None:
        recipe = self._require_edit()
        if field not in {"brightness", "contrast", "saturation", "strength"}:
            raise ValueError("Choose a brightness, contrast, saturation or strength adjustment.")
        updated = update_tone(recipe, replace(recipe.tone, **{field: value}))
        if updated is not recipe:
            self._change(updated)

    def reset_tone(self) -> None:
        recipe = self._require_edit()
        updated = update_tone(recipe, PhotoTone())
        if updated is not recipe:
            self._change(updated)

    def add_ellipse(self, cx: float, cy: float, rx: float, ry: float) -> None:
        self._require_eye_edit()
        recipe = self._require_edit()
        ids = {eye.id for eye in recipe.eyes}
        self._manual_number += 1
        while (eye_id := f"manual-{self._manual_number}") in ids:
            self._manual_number += 1
        eye = self._tools.manual(recipe.source, eye_id=eye_id, cx=cx, cy=cy, rx=rx, ry=ry)
        self.selected_id = eye.id
        self._change(replace(recipe, eyes=(*recipe.eyes, eye)))

    def replace_ellipse(
        self,
        eye_id: str,
        cx: float,
        cy: float,
        rx: float,
        ry: float,
    ) -> None:
        self._require_eye_edit()
        eye = self._eye(eye_id)
        assert self.recipe is not None
        adjusted = self._tools.manual(
            self.recipe.source, eye_id=eye_id, cx=cx, cy=cy, rx=rx, ry=ry, strength=eye.strength
        )
        self._replace(eye_id, adjusted)

    def _replace(self, eye_id: str, replacement: EyeEdit) -> None:
        recipe = self._require_edit()
        self._change(
            replace(
                recipe, eyes=tuple(replacement if eye.id == eye_id else eye for eye in recipe.eyes)
            )
        )

    def remove_eye(self, eye_id: str) -> None:
        self._require_eye_edit()
        self._eye(eye_id)
        assert self.recipe is not None
        eyes = tuple(eye for eye in self.recipe.eyes if eye.id != eye_id)
        if self.selected_id == eye_id:
            self.selected_id = eyes[0].id if eyes else ""
        self._change(replace(self.recipe, eyes=eyes))

    def _change(self, recipe: PhotoEditRecipe) -> None:
        previous = self._require_edit()
        if not self._gesture or not self._gesture_saved:
            self._undo.append(previous)
            self._gesture_saved = self._gesture
        self.recipe = recipe
        self._restore_selection()
        self.error = ""
        self.request_preview()

    def begin_gesture(self) -> None:
        self._require_edit()
        self._gesture, self._gesture_saved = True, False

    def end_gesture(self) -> None:
        self._gesture = self._gesture_saved = False

    def undo(self) -> None:
        self._require_edit()
        self.end_gesture()
        if self._undo:
            self.recipe = self._undo.pop()
            self._restore_selection()
            self.error = ""
            self.request_preview()

    def reset(self) -> None:
        self._require_edit()
        if self._initial is not None and self.recipe is not self._initial:
            self._change(self._initial)
            self._restore_selection()

    def _restore_selection(self) -> None:
        assert self.recipe is not None
        if self.selected_id not in {eye.id for eye in self.recipe.eyes}:
            self.selected_id = self.recipe.eyes[0].id if self.recipe.eyes else ""

    def request_preview(self) -> None:
        recipe = self._require_edit()
        self.generation += 1
        request = PhotoEditRequest(
            "preview", self.generation, recipe=recipe, selected_id=self.selected_id or None
        )
        if self._inflight is not None or self._worker_busy:
            self._pending = request
        else:
            self._submit(request)
        self._changed()

    def save(self) -> None:
        if not self.can_save:
            raise ActionBlockedError("Wait for a valid preview before saving the photo edit.")
        self.end_gesture()
        self.generation += 1
        self._submit(PhotoEditRequest("save", self.generation, recipe=self.recipe))
        self._changed()

    def close(self, discard_confirmed: bool = False) -> bool:
        if not self.active and self._inflight is None:
            return True
        if self.dirty and not discard_confirmed:
            return False
        if self._inflight is not None:
            self._controller._worker.cancel()
        self.generation += 1
        self.active = False
        self._inflight = self._pending = None
        self.recipe = self._initial = self._clean = None
        self._undo.clear()
        self.selected_id, self.error = "", ""
        self.geometry_mode = False
        self.end_gesture()
        self._forget_preview()
        self._changed()
        return True

    def _discard_preview(
        self, preview: PhotoPreview | None, *, keeping: PhotoPreview | None = None
    ) -> None:
        for path in _preview_paths(preview) - _preview_paths(keeping):
            if path.parent == self._cache_dir:
                with suppress(OSError):
                    path.unlink()

    def _forget_preview(self) -> None:
        self._discard_preview(self.preview)
        self.preview = None
        with suppress(OSError):
            self._cache_dir.rmdir()

    def report_error(self, message: str) -> None:
        """Show ``message`` as the review's error and tell the page."""
        self.error = message
        self._changed()

    def _changed(self) -> None:
        self._controller._changed()
