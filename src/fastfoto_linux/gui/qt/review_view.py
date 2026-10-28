"""The QML review contract and its debounced sidecar autosave."""

import functools
import logging
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot

from fastfoto_linux.documents.cleanup import CleanupStatus, page_cleanup
from fastfoto_linux.documents.draft import DocumentDraft, PageAnalysis
from fastfoto_linux.documents.draft_edit import parts
from fastfoto_linux.documents.modes import CleanupPolicy, ColourMode, ColourPolicy
from fastfoto_linux.gui import reviewcrop
from fastfoto_linux.gui.qt.photos_model import file_url
from fastfoto_linux.gui.qt.review_model import ReviewModel
from fastfoto_linux.gui.qt.slotargs import confirmed_flag
from fastfoto_linux.gui.report import Banner
from fastfoto_linux.gui.review import (
    MODE_LABELS,
    colour_values,
    preview_cleanup_text,
    preview_despeckle_text,
    review_items,
    review_summary,
)

if TYPE_CHECKING:
    from fastfoto_linux.gui.qt.bridge import Bridge

logger = logging.getLogger(__name__)
AUTOSAVE_MS = 500
CROP_CENTRE = 500  # permille: the middle of the page
NO_CLEANUP_TEXT = " — without paper cleanup"


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
        settings = self._side._settings
        policy = settings.colour if settings else ColourPolicy.COLOUR
        self._items.set_items(review_items(state, policy, self._known_cleanup()) if state else ())
        if state and state.draft is not self._last_draft:
            self._last_draft = state.draft
            if self._side.dirty:
                self._timer.start()
        self.changed.emit()

    def _known_cleanup(self) -> dict[int, CleanupStatus]:
        """The previewed page's cleanup result, while the page's level is still the rendered one."""
        side, cached = self._side, self._side._preview_cached
        status = side.preview_cleanup_status
        if status is None or cached is None or side.state is None or not cached.cleaned:
            return {}
        page = side.state.draft.pages[side.preview_number - 1]
        # Every edit that changes pixels restarts the preview (and clears the status), so this
        # level check is only a backstop against a status that outlived its draft.
        if page_cleanup(cached.draft, page) is not page_cleanup(side.state.draft, page):
            return {}
        return {side.preview_number: status}

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

    @Property(str, notify=changed)
    def previewView(self) -> str:
        return self._side.preview_view

    @Property(bool, notify=changed)
    def previewCleaned(self) -> bool:
        return self._side.preview_cleaned

    @Property(bool, notify=changed)
    def previewCropMode(self) -> bool:
        """True when the source preview and its size are here, so a crop can be drawn on it."""
        side = self._side
        return bool(
            side.preview_view == "source" and side.preview_path and side.preview_size is not None
        )

    @Property("QVariantList", notify=changed)
    def previewCropRect(self) -> list[int]:
        return reviewcrop.crop_rectangle(self._side)

    @Property(int, notify=changed)
    def previewSourceWidth(self) -> int:
        return self._side.preview_size[0] if self._side.preview_size else 0

    @Property(int, notify=changed)
    def previewSourceHeight(self) -> int:
        return self._side.preview_size[1] if self._side.preview_size else 0

    @Property(bool, notify=changed)
    def previewActual(self) -> bool:
        return self._side.preview_crop is not None

    @Property(int, notify=changed)
    def previewCropX(self) -> int:
        crop = self._side.preview_crop
        return crop[0] if crop else CROP_CENTRE

    @Property(int, notify=changed)
    def previewCropY(self) -> int:
        crop = self._side.preview_crop
        return crop[1] if crop else CROP_CENTRE

    @Property(bool, notify=changed)
    def previewCleanupAvailable(self) -> bool:
        """True when the previewed page has a cleanup level to compare with its original."""
        state, number = self._side.state, self._side.preview_target
        if state is None or not number:
            return False
        page = state.draft.pages[number - 1]
        mode = colour_values(state.draft, page, self._side._settings.colour)[1]
        if mode == ColourMode.BW.value:
            return state.draft.despeckle
        return page_cleanup(state.draft, page) is not CleanupPolicy.OFF

    @Property(bool, notify=changed)
    def previewSwitchSpecks(self) -> bool:
        """True when the preview switch compares specks removal (a black and white page), not
        paper cleanup, which black and white never has."""
        state, number = self._side.state, self._side.preview_target
        if state is None or not number:
            return False
        page = state.draft.pages[number - 1]
        return colour_values(state.draft, page, self._side._settings.colour)[1] == "bw"

    @Property(str, notify=changed)
    def documentCleanup(self) -> str:
        return self._side.state.draft.cleanup.value if self._side.state else CleanupPolicy.OFF.value

    @Property(bool, notify=changed)
    def documentDespeckle(self) -> bool:
        return self._side.state.draft.despeckle if self._side.state else False

    @Property(str, notify=changed)
    def previewLabel(self) -> str:
        if self._side.preview_view == "source":
            return "Source preview"
        if self._side.preview_path is None:
            return "Preparing output preview…"
        state = self._side.state
        if state is None:
            return "Output preview"
        page = state.draft.pages[self._side.preview_number - 1]
        values = colour_values(state.draft, page, self._side._settings.colour)
        mode = MODE_LABELS.get(values[1], "")
        label = f"Output: {mode}" if mode else "Output preview"
        return label + self._preview_label_suffix(state.draft, page, values[1])

    def _preview_label_suffix(self, draft: DocumentDraft, page: PageAnalysis, mode: str) -> str:
        suffix = ""
        level = page_cleanup(draft, page)
        if mode == ColourMode.BW.value and draft.despeckle:
            if self._side.preview_cleaned:
                suffix = " — " + preview_despeckle_text(self._side.preview_despeckle_status)
            else:
                suffix = " — without removing specks"
        elif mode != ColourMode.BW.value and level is not CleanupPolicy.OFF:
            if self._side.preview_cleaned:
                suffix = " — " + preview_cleanup_text(level, self._side.preview_cleanup_status)
            else:
                suffix = NO_CLEANUP_TEXT
        return suffix + (" — actual pixels" if self._side.preview_crop is not None else "")

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
        self._call(self._set_colour, number, value)

    def _set_colour(self, number: int, value: str) -> None:
        policy = ColourPolicy(value) if value else None
        self._side.edit("set_colour", number, policy)

    @Slot(int, str)
    def setCleanup(self, number: int, value: str) -> None:
        self._call(self._set_cleanup, number, value)

    def _set_cleanup(self, number: int, value: str) -> None:
        self._side.edit("set_cleanup", number, CleanupPolicy(value) if value else None)

    @Slot(str)
    def setDocumentCleanup(self, value: str) -> None:
        self._call(self._side.edit, "set_document_cleanup", CleanupPolicy(value))

    @Slot(bool)
    def setDocumentDespeckle(self, value: bool) -> None:
        self._call(self._side.edit, "set_document_despeckle", value)

    @Slot(int, int)
    def rotate(self, number: int, turns: int) -> None:
        self._call(self._side.edit, "rotate", number, turns)

    @Slot(int, int, int, int, int, result=bool)
    def setCrop(self, number: int, left: int, top: int, right: int, bottom: int) -> bool:
        return bool(self._call(reviewcrop.store_crop, self._side, number, left, top, right, bottom))

    @Slot(int, result=bool)
    def clearCrop(self, number: int) -> bool:
        return bool(self._call(reviewcrop.clear_crop, self._side, number))

    @Slot(int, float, float, float, float, float, float, float, float, result=bool)
    def cropFromDrag(  # noqa: PLR0913, PLR0917 - the drag and the painted geometry
        self,
        number: int,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        pw: float,
        ph: float,
        iw: float,
        ih: float,
    ) -> bool:
        """False when the drag is under 5 mm on a side (or unusable): nothing is stored."""
        drag = functools.partial(
            reviewcrop.crop_from_drag,
            painted_width=pw,
            painted_height=ph,
            item_width=iw,
            item_height=ih,
        )
        return bool(self._call(drag, self._side, number, x0, y0, x1, y1))

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
        return self._call(self._side.preview, number, view) or ""

    @Slot(int, bool, bool, int, int, result=str)
    def previewOptions(self, number: int, cleaned: bool, actual: bool, x: int, y: int) -> str:
        crop = (x, y) if actual else None
        return self._call(self._preview_output, number, cleaned, crop) or ""

    def _preview_output(self, number: int, cleaned: bool, crop: tuple[int, int] | None) -> str:
        return self._side.preview(number, "output", cleaned=cleaned, crop=crop)

    @Slot("QVariant")
    def deleteOriginals(self, confirmed: object = False) -> None:
        self._call(lambda: self._side.delete_originals(confirmed_flag(confirmed)))
