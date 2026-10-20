"""The public QML photo editor interface, backed by one Qt-free controller component."""

import logging
from collections.abc import Callable
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

import numpy as np
from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot

from fastfoto_linux.gui.qt.photos_model import file_url
from fastfoto_linux.gui.state import ActionBlockedError
from fastfoto_linux.photo_edits import (
    EyeEdit,
    PhotoEditError,
    PhotoGeometry,
    PhotoTone,
    frame_size,
    min_crop_size,
    output_size,
    straightened_size,
)

if TYPE_CHECKING:
    from fastfoto_linux.gui.photoeditside import PhotoEditSide
    from fastfoto_linux.gui.qt.bridge import Bridge

logger = logging.getLogger(__name__)

MM_PER_INCH = 25.4
DEFAULT_EYE_RADIUS_MM = 0.6
GENERIC_ERROR = "Something went wrong with the photo edit. See the log for details."
GENERIC_FILE_ERROR = "The photo or its saved edit could not be read or written."


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
        path = getattr(preview, name) if preview else None
        return file_url(path) if path else ""

    @Property(str, notify=changed)
    def beforeUrl(self) -> str:
        return self._url("before")

    @Property(str, notify=changed)
    def afterUrl(self) -> str:
        return self._url("after")

    @Property(str, notify=changed)
    def workingUrl(self) -> str:
        # Identical to the after image while the geometry is neutral.
        return self._url("working") or self._url("after")

    @Property(str, notify=changed)
    def straightenedUrl(self) -> str:
        # The straightened frame, else the working image (the source frame at angle 0).
        return self._url("straightened") or self.workingUrl

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

    @Property(bool, notify=changed)
    def geometryMode(self) -> bool:
        return self._side.geometry_mode

    @Property(bool, notify=changed)
    def geometryNeutral(self) -> bool:
        recipe = self._side.recipe
        return recipe is None or recipe.geometry == PhotoGeometry()

    @Property(bool, notify=changed)
    def canEditEyes(self) -> bool:
        return self._side.can_edit_eyes

    @Property("QVariantMap", notify=changed)
    def geometry(self) -> dict[str, object]:
        recipe = self._side.recipe
        if recipe is None:
            return dict(quarterTurns=0, cropped=False, crop=[0, 0, 0, 0])
        geometry = recipe.geometry
        full = (0, 0, *frame_size(recipe.source, geometry))
        return dict(
            quarterTurns=geometry.quarter_turns,
            cropped=geometry.crop is not None,
            crop=list(geometry.crop or full),
            straightenTenths=geometry.straighten_tenths,
        )

    def _frame(self) -> tuple[int, int]:
        recipe = self._side.recipe
        return frame_size(recipe.source, recipe.geometry) if recipe else (0, 0)

    @Property(int, notify=changed)
    def frameWidth(self) -> int:
        return self._frame()[0]

    @Property(int, notify=changed)
    def frameHeight(self) -> int:
        return self._frame()[1]

    def _shown_frame(self) -> tuple[int, int]:
        """The frame the held preview was built for, which may lag the draft's frame."""
        side = self._side
        if side.recipe is None:
            return (0, 0)
        source = side.recipe.source
        return straightened_size(source.width, source.height, side.preview_tenths or 0)

    @Property(int, notify=changed)
    def shownFrameWidth(self) -> int:
        return self._shown_frame()[0]

    @Property(int, notify=changed)
    def shownFrameHeight(self) -> int:
        return self._shown_frame()[1]

    @Property(bool, notify=changed)
    def canStraighten(self) -> bool:
        return self._side.can_straighten

    @Property(bool, notify=changed)
    def previewCurrent(self) -> bool:
        return self._side.preview_current

    def _output(self) -> tuple[int, int]:
        recipe = self._side.recipe
        return output_size(recipe.source, recipe.geometry) if recipe else (0, 0)

    @Property(int, notify=changed)
    def outputWidth(self) -> int:
        return self._output()[0]

    @Property(int, notify=changed)
    def outputHeight(self) -> int:
        return self._output()[1]

    def _min_crop(self) -> tuple[int, int]:
        recipe = self._side.recipe
        return min_crop_size(recipe.source, recipe.geometry) if recipe else (0, 0)

    @Property(int, notify=changed)
    def minCropWidth(self) -> int:
        return self._min_crop()[0]

    @Property(int, notify=changed)
    def minCropHeight(self) -> int:
        return self._min_crop()[1]

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
        return self._side.can_edit

    @Property(str, notify=changed)
    def savedEditUrl(self) -> str:
        return file_url(self._side.saved_edit.sidecar) if self._side.saved_edit else ""

    def _call(self, action: Callable[..., Any], *args: object) -> Any:
        try:
            return action(*args)
        except (PhotoEditError, ActionBlockedError, ValueError) as error:
            # These carry messages written for the user.
            self._side.report_error(str(error))
        except OSError:
            # The OS text can hold a path, so it goes to the log, never to the page.
            logger.exception("photo edit action failed")
            self._side.report_error(GENERIC_FILE_ERROR)
        except Exception:
            # A bug must not escape the Qt slot; its text may hold paths, so only the log gets it.
            logger.exception("unexpected photo edit failure")
            self._side.report_error(GENERIC_ERROR)
        return None

    @Slot(int)
    def openPhoto(self, row: int) -> None:
        self._call(self._side.open_photo, row)

    @Slot(QUrl)
    def openSavedEdit(self, url: QUrl) -> None:
        if not url.isLocalFile():
            self._side.report_error("Choose a local saved edit JSON file.")
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

    @Slot(bool)
    def setGeometryMode(self, value: bool) -> None:
        self._call(self._side.set_geometry_mode, value)

    @Slot()
    def rotateClockwise(self) -> None:
        self._call(self._side.rotate, True)

    @Slot()
    def rotateCounterclockwise(self) -> None:
        self._call(self._side.rotate, False)

    @Slot(int, int, int, int)
    def setCrop(self, left: int, top: int, right: int, bottom: int) -> None:
        self._call(self._side.set_crop, left, top, right, bottom)

    @Slot()
    def clearCrop(self) -> None:
        self._call(self._side.clear_crop)

    @Slot(int)
    def setStraighten(self, tenths: int) -> None:
        self._call(self._side.set_straighten, tenths)

    @Slot()
    def resetStraighten(self) -> None:
        self._call(self._side.reset_straighten)

    @Slot()
    def resetGeometry(self) -> None:
        self._call(self._side.reset_geometry)

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
