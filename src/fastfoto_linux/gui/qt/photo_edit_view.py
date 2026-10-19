"""The public QML photo editor interface, backed by one Qt-free controller component."""

from collections.abc import Callable
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

import numpy as np
from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot

from fastfoto_linux.gui.qt.photos_model import file_url
from fastfoto_linux.photo_edits import EyeEdit, PhotoTone

if TYPE_CHECKING:
    from fastfoto_linux.gui.photoeditside import PhotoEditSide
    from fastfoto_linux.gui.qt.bridge import Bridge

MM_PER_INCH = 25.4
DEFAULT_EYE_RADIUS_MM = 0.6


def _candidate(eye: EyeEdit) -> dict[str, object]:
    ys = np.flatnonzero(eye.mask.any(axis=1))
    xs = np.flatnonzero(eye.mask.any(axis=0))
    return dict(
        id=eye.id,
        origin=eye.origin,
        roi=list(eye.roi),
        center=list(eye.center),
        accepted=eye.accepted,
        strength=eye.strength,
        radiusX=max(0.5, (int(xs.max()) - int(xs.min()) + 1) / 2),
        radiusY=max(0.5, (int(ys.max()) - int(ys.min()) + 1) / 2),
    )


class PhotoEditView(QObject):
    changed = Signal()
    closeConfirmationRequired = Signal()

    def __init__(self, bridge: "Bridge") -> None:
        super().__init__(bridge)
        self._controller = bridge.controller

    @property
    def _side(self) -> "PhotoEditSide":
        return self._controller.photo_edit

    def refresh(self) -> None:
        self.changed.emit()

    def stop(self) -> None:
        self._side.close(discard_confirmed=True)

    @Property(bool, notify=changed)
    def active(self) -> bool:
        return self._side.active

    @Property(bool, notify=changed)
    def busy(self) -> bool:
        return self._side.busy

    @Property(bool, notify=changed)
    def dirty(self) -> bool:
        return self._side.dirty

    @Property(str, notify=changed)
    def error(self) -> str:
        return self._side.error

    @Property(str, notify=changed)
    def sourceLabel(self) -> str:
        return "Retained cropped, upright original JPEG. Photo edits save a new copy."

    @Property(str, notify=changed)
    def warning(self) -> str:
        recipe = self._side.recipe
        return "\n".join(recipe.source.warnings) if recipe else ""

    def _url(self, name: str) -> str:
        preview = self._side.preview
        return file_url(getattr(preview, name)) if preview else ""

    @Property(str, notify=changed)
    def beforeUrl(self) -> str:
        return self._url("before")

    @Property(str, notify=changed)
    def afterUrl(self) -> str:
        return self._url("after")

    @Property(str, notify=changed)
    def roiBeforeUrl(self) -> str:
        return self._url("roi_before")

    @Property(str, notify=changed)
    def roiAfterUrl(self) -> str:
        return self._url("roi_after")

    @Property(int, notify=changed)
    def sourceWidth(self) -> int:
        return self._side.recipe.source.width if self._side.recipe else 0

    @Property(int, notify=changed)
    def sourceHeight(self) -> int:
        return self._side.recipe.source.height if self._side.recipe else 0

    @Property(float, notify=changed)
    def defaultRadius(self) -> float:
        dpi = self._side.recipe.source.effective_dpi if self._side.recipe else 300
        return DEFAULT_EYE_RADIUS_MM * dpi / MM_PER_INCH

    @Property("QVariantList", notify=changed)
    def candidates(self) -> list[dict[str, object]]:
        return [_candidate(eye) for eye in self._side.recipe.eyes] if self._side.recipe else []

    @Property("QVariantMap", notify=changed)
    def tone(self) -> dict[str, int]:
        recipe = self._side.recipe
        return asdict(recipe.tone if recipe else PhotoTone())

    @Property(str, notify=changed)
    def selectedId(self) -> str:
        return self._side.selected_id

    @Property(bool, notify=changed)
    def canUndo(self) -> bool:
        return self._side.can_undo

    @Property(bool, notify=changed)
    def canReset(self) -> bool:
        return self._side.can_reset

    @Property(bool, notify=changed)
    def canSave(self) -> bool:
        return self._side.can_save

    @Property(bool, notify=changed)
    def canEdit(self) -> bool:
        return self._side._can_edit

    @Property(str, notify=changed)
    def savedEditUrl(self) -> str:
        return file_url(self._side.saved_edit.sidecar) if self._side.saved_edit else ""

    def _call(self, action: Callable[..., Any], *args: object) -> Any:
        try:
            return action(*args)
        except Exception as error:
            self._side.error = str(error)
            self._controller._changed()
            return None

    @Slot(int)
    def openPhoto(self, row: int) -> None:
        self._call(self._side.open_photo, row)

    @Slot(QUrl)
    def openSavedEdit(self, url: QUrl) -> None:
        if not url.isLocalFile():
            self._side.error = "Choose a local saved edit JSON file."
            self._controller._changed()
            return
        from pathlib import Path  # noqa: PLC0415 - local URL conversion

        self._call(self._side.open_saved, Path(url.toLocalFile()))

    @Slot(str)
    def selectEye(self, eye_id: str) -> None:
        self._call(self._side.select_eye, eye_id)

    @Slot(str, bool)
    def setAccepted(self, eye_id: str, value: bool) -> None:
        self._call(self._side.set_accepted, eye_id, value)

    @Slot(str, int)
    def setStrength(self, eye_id: str, value: int) -> None:
        self._call(self._side.set_strength, eye_id, value)

    @Slot(str, int)
    def setTone(self, field: str, value: int) -> None:
        self._call(self._side.set_tone, field, value)

    @Slot()
    def resetTone(self) -> None:
        self._call(self._side.reset_tone)

    @Slot(float, float, float, float)
    def addEllipse(self, cx: float, cy: float, rx: float, ry: float) -> None:
        self._call(self._side.add_ellipse, cx, cy, rx, ry)

    @Slot(str, float, float, float, float)
    def replaceEllipse(
        self,
        eye_id: str,
        cx: float,
        cy: float,
        rx: float,
        ry: float,
    ) -> None:
        self._call(self._side.replace_ellipse, eye_id, cx, cy, rx, ry)

    @Slot(str)
    def removeEye(self, eye_id: str) -> None:
        self._call(self._side.remove_eye, eye_id)

    @Slot()
    def beginGesture(self) -> None:
        self._call(self._side.begin_gesture)

    @Slot()
    def endGesture(self) -> None:
        self._side.end_gesture()

    @Slot()
    def undo(self) -> None:
        self._call(self._side.undo)

    @Slot()
    def reset(self) -> None:
        self._call(self._side.reset)

    @Slot()
    def save(self) -> None:
        self._call(self._side.save)

    @Slot(result=bool)
    @Slot(bool, result=bool)
    def close(self, discard_confirmed: bool = False) -> bool:
        answer = self._side.close(discard_confirmed)
        if not answer:
            self.closeConfirmationRequired.emit()
        return answer
