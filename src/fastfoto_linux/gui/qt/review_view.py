"""The QML review contract and its debounced sidecar autosave."""

import logging
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot

from fastfoto_linux.documents.draft_edit import parts
from fastfoto_linux.gui.qt.photos_model import file_url
from fastfoto_linux.gui.qt.review_model import ReviewModel
from fastfoto_linux.gui.report import Banner
from fastfoto_linux.gui.review import review_items, review_summary

if TYPE_CHECKING:
    from fastfoto_linux.gui.qt.bridge import Bridge

logger = logging.getLogger(__name__)
AUTOSAVE_MS = 500


class ReviewView(QObject):
    changed = Signal()

    def __init__(self, bridge: "Bridge") -> None:
        super().__init__(bridge)
        self._controller = bridge.controller
        self._side = bridge.controller.review
        self._items = ReviewModel(self)
        self._last_draft = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(AUTOSAVE_MS)
        self._timer.timeout.connect(self.flush)

    def stop(self) -> None:
        # Qt may already have deleted the bridge and its child timer.
        with suppress(RuntimeError):
            self._timer.stop()

    def refresh(self) -> None:
        state = self._side.state
        self._items.set_items(review_items(state) if state else ())
        if state and state.draft is not self._last_draft:
            self._last_draft = state.draft
            if self._side.dirty:
                self._timer.start()
        self.changed.emit()

    @Property(bool, notify=changed)
    def active(self) -> bool:
        return self._side.active

    @Property(QObject, constant=True)
    def items(self) -> ReviewModel:
        return self._items

    @Property(str, notify=changed)
    def summary(self) -> str:
        return review_summary(self._side.state) if self._side.state else ""

    @Property(bool, notify=changed)
    def canSave(self) -> bool:
        return self._side.can_save

    @Property(int, notify=changed)
    def flaggedCount(self) -> int:
        state = self._side.state
        return sum(bool(page.flags) for page in state.draft.pages) if state else 0

    @Property(bool, notify=changed)
    def flaggedOnly(self) -> bool:
        return self._side.state.flagged_only if self._side.state else False

    @Property(int, notify=changed)
    def focusNumber(self) -> int:
        return self._side.state.focus if self._side.state else 0

    @Property("QVariantList", notify=changed)
    def parts(self) -> list[dict[str, object]]:
        state, settings = self._side.state, self._side._settings
        if state is None or settings is None:
            return []
        return [
            {"number": i, "name": part.name or settings.name, "pages": len(part.pages)}
            for i, part in enumerate(parts(state.draft), 1)
        ]

    @Property(str, notify=changed)
    def rawRootUrl(self) -> str:
        return file_url(Path(self._controller.form.output_folder).expanduser() / ".raw")

    @Property(bool, notify=changed)
    def canDeleteOriginals(self) -> bool:
        return self._side.can_delete_originals

    @Property(bool, notify=changed)
    def canReopen(self) -> bool:
        return self._side.can_reopen

    @Property(str, notify=changed)
    def previewUrl(self) -> str:
        return file_url(self._side.preview_path)

    @Property(int, notify=changed)
    def previewNumber(self) -> int:
        return self._side.preview_number

    def _call(self, action: Callable[..., Any], *args: object) -> Any:
        try:
            answer = action(*args)
        except Exception as error:
            logger.warning("document review action failed: %s", error)
            self._controller._banner = Banner("error", str(error))
            self._controller._changed()
            answer = None
        self.refresh()
        return answer

    @Slot()
    def enable(self) -> None:
        self._side.enable()

    @Slot(int)
    def toggle(self, number: int) -> None:
        self._call(self._side.edit, "toggle", number)

    @Slot(int, str)
    def setColour(self, number: int, value: str) -> None:
        raise NotImplementedError("per-page review colour is not implemented")

    @Slot(int, int)
    def rotate(self, number: int, turns: int) -> None:
        self._call(self._side.edit, "rotate", number, turns)

    @Slot(int, int)
    def move(self, number: int, to: int) -> None:
        self._call(self._side.edit, "move", number, to)

    @Slot(int)
    def toggleSplit(self, number: int) -> None:
        self._call(self._side.edit, "toggle_split", number)

    @Slot(int, str, result=bool)
    def setPartName(self, number: int, name: str) -> bool:
        return bool(self._call(self._side.edit, "name_part", number, name))

    @Slot(bool)
    def setFlaggedOnly(self, enabled: bool) -> None:
        self._call(self._side.edit, "only_flagged", enabled)

    @Slot(int)
    def focus(self, number: int) -> None:
        self._call(self._side.edit, "focused", number)

    @Slot()
    def save(self) -> None:
        self._timer.stop()
        self._call(self._side.save)

    @Slot()
    def back(self) -> None:
        self._timer.stop()
        self._call(self._side.back)

    @Slot(QUrl)
    def openFolder(self, url: QUrl) -> None:
        if not url.isLocalFile():
            self._call(self._reject_url)
            return
        self._timer.stop()
        self._call(self._side.open_folder, Path(url.toLocalFile()))

    def _reject_url(self) -> None:
        raise ValueError("choose a local folder of original pages")

    @Slot()
    def reopen(self) -> None:
        self._call(self._side.reopen)

    @Slot(result=bool)
    def flush(self) -> bool:
        self._timer.stop()
        return self._side.flush()

    @Slot(int, result=str)
    def preview(self, number: int) -> str:
        return self._call(self._side.preview, number) or ""

    @Slot(int, str, result=str)
    def previewMode(self, number: int, view: str) -> str:
        raise NotImplementedError("output preview selection is not implemented")

    @Slot(bool)
    def deleteOriginals(self, confirmed: bool = False) -> None:
        self._call(self._side.delete_originals, confirmed)
