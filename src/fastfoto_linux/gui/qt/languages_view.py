"""Asynchronous local OCR inventory and explicit model downloads for the language picker."""

import threading
from collections.abc import Callable, Sequence
from typing import Any

from PySide6.QtCore import Property, QObject, Qt, Signal, Slot

from fastfoto_linux.documents import OcrCancelledError, ocr_languages
from fastfoto_linux.documents.ocr_downloads import download_languages
from fastfoto_linux.documents.ocr_languages import Inventory
from fastfoto_linux.gui.controller import Controller
from fastfoto_linux.gui.languages import (
    download_codes,
    format_bytes,
    language_rows,
    language_summary,
    missing_languages,
    selected_codes,
    toggle_language,
)


class LanguagesView(QObject):
    changed = Signal()
    _answer = Signal(str, object)

    def __init__(
        self,
        controller: Controller,
        parent: QObject | None = None,
        *,
        discover: Callable[..., Inventory] | None = None,
        download: Callable[..., None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._discover = discover or ocr_languages.discover_languages
        self._download = download or download_languages
        self._inventory = Inventory(())
        self._search = ""
        self._message = ""
        self._busy = False
        self._downloading = False
        self._loaded = False
        self._closed = False
        self._cancel = threading.Event()
        self._emit_lock = threading.Lock()
        self._progress: tuple[str, int, int] = ("", 0, 0)
        self._answer.connect(self._receive, Qt.ConnectionType.QueuedConnection)
        if parent is not None:
            parent.destroyed.connect(lambda _object: self.stop())

    @property
    def _langs(self) -> str:
        return self._controller.document_form.langs

    @Property("QVariantList", notify=changed)
    def rows(self) -> list[dict[str, Any]]:
        return language_rows(self._inventory, self._langs, self._search)

    @Property(str, notify=changed)
    def summary(self) -> str:
        return language_summary(self._inventory, self._langs)

    @Property(bool, notify=changed)
    def busy(self) -> bool:
        return self._busy

    @Property(bool, notify=changed)
    def ready(self) -> bool:
        return (
            self._loaded
            and not self._busy
            and not self._inventory.error
            and bool(selected_codes(self._langs))
            and not missing_languages(self._inventory, self._langs)
        )

    @Property(bool, notify=changed)
    def canDownload(self) -> bool:
        return (
            self._loaded
            and not self._busy
            and not self._controller.busy
            and bool(download_codes(self._inventory, self._langs))
        )

    @Property(str, notify=changed)
    def message(self) -> str:
        return self._message or self._inventory.error

    @Property(str, notify=changed)
    def scanMessage(self) -> str:
        if self._busy:
            return "Wait for the text language check or download to finish before scanning."
        if not self._loaded or self._inventory.error:
            return self.message or "Check the installed text languages before scanning."
        if not selected_codes(self._langs):
            return "Choose at least one text language before scanning."
        missing = missing_languages(self._inventory, self._langs)
        if missing:
            downloadable = download_codes(self._inventory, self._langs)
            custom_hint = (
                " Custom languages must be installed locally."
                if any(code not in downloadable for code in missing)
                else ""
            )
            return (
                f"Text language data is missing: {', '.join(missing)}. "
                f"Use Download selected languages, then scan.{custom_hint}"
            )
        return ""

    @Property(str, notify=changed)
    def downloadText(self) -> str:
        codes = download_codes(self._inventory, self._langs)
        languages = self._inventory.languages
        if self._inventory.orientation is not None:
            languages = (*languages, self._inventory.orientation)
        total = sum(language.size for language in languages if language.code in codes)
        if not codes:
            return "Selected languages are ready for offline use." if self.ready else ""
        orientation = " Includes orientation data (osd)." if "osd" in codes else ""
        model_word = "model" if len(codes) == 1 else "models"
        return f"Download {len(codes)} {model_word} · {format_bytes(total)}.{orientation}"

    @Property(str, notify=changed)
    def progressText(self) -> str:
        code, received, total = self._progress
        if not code:
            if self._busy and self._downloading:
                return "Preparing selected language downloads…"
            return "Checking installed text languages…" if self._busy else ""
        return f"Downloading {code}: {format_bytes(received)} / {format_bytes(total)}"

    @Property(float, notify=changed)
    def progress(self) -> float:
        _, received, total = self._progress
        return received / total if total else 0.0

    @Slot(str)
    def setSearch(self, text: str) -> None:
        self._search = text
        self.changed.emit()

    @Slot(str, bool)
    def setSelected(self, code: str, checked: bool) -> None:
        known = {language.code for language in self._inventory.languages}
        if self._busy or self._closed or self._controller.busy:
            return
        if code not in known and code not in selected_codes(self._langs):
            return
        wanted = toggle_language(self._langs, code, checked)
        if wanted == self._langs:
            return
        self._controller.set_document_field("langs", wanted)
        self.changed.emit()

    @Slot()
    def reload(self) -> None:
        if not self._busy and not self._closed and not self._controller.busy:
            self._start(None)

    @Slot()
    def downloadSelected(self) -> None:
        if self.canDownload:
            self._start(download_codes(self._inventory, self._langs))

    def _start(self, codes: tuple[str, ...] | None) -> None:
        self._busy = True
        self._downloading = codes is not None
        if codes is None:
            self._loaded = False
        self._message = ""
        self._progress = ("", 0, 0)
        self._cancel = threading.Event()
        threading.Thread(
            target=self._run, args=(codes, self._cancel), name="fastfoto-languages", daemon=True
        ).start()
        self.changed.emit()

    def _run(self, codes: Sequence[str] | None, cancel: threading.Event) -> None:
        try:
            if codes is not None:
                self._download(codes, cancel=cancel, progress=self._report_progress)
            answer = self._discover(cancel=cancel)
            self._post("done", (answer, ""))
        except OcrCancelledError:
            self._post("done", (None, "Language check or download cancelled. You can retry."))
        except Exception as error:
            self._post("done", (None, str(error)))

    def _report_progress(self, code: str, received: int, total: int) -> None:
        self._post("progress", (code, received, total))

    def _post(self, kind: str, answer: object) -> None:
        with self._emit_lock:
            if not self._closed:
                try:
                    self._answer.emit(kind, answer)
                except RuntimeError:
                    self._closed = True
                    self._cancel.set()

    @Slot(str, object)
    def _receive(self, kind: str, answer: Any) -> None:
        if self._closed:
            return
        if kind == "progress":
            self._progress = answer
        else:
            inventory, self._message = answer
            if inventory is not None:
                self._inventory = inventory
                self._loaded = True
            self._busy = False
            self._downloading = False
            self._progress = ("", 0, 0)
        self.changed.emit()

    @Slot()
    def cancel(self) -> None:
        self._cancel.set()

    def stop(self) -> None:
        with self._emit_lock:
            self._closed = True
        self._cancel.set()
