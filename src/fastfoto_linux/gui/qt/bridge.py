"""The object QML talks to: the controller's properties and slots, on the GUI thread."""

import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QObject, Qt, QUrl, Signal, Slot

from fastfoto_linux.gui.controller import Controller
from fastfoto_linux.gui.form import BACK_CHOICES, FEED_CHOICES, ScanForm
from fastfoto_linux.gui.prefs import load_form, save_form
from fastfoto_linux.gui.qt.photos_model import PhotosModel, file_url
from fastfoto_linux.gui.worker import DiscoverFn, ProcessFn, SessionFn, Worker
from fastfoto_linux.scanner import SUPPORTED_DPI

logger = logging.getLogger(__name__)

JOIN_TIMEOUT = 30.0  # seconds to wait for a cancelled job to wind down on shutdown


class Bridge(QObject):
    """Owns the worker and the controller; the worker's events cross to the GUI thread here.

    The worker calls the ``on_*`` sink methods on its own thread. Each one only emits a queued
    signal, so the controller (and everything QML reads) is only ever touched on the GUI thread.
    """

    changed = Signal()
    closeReady = Signal()
    _event = Signal(str, object)

    def __init__(
        self,
        *,
        form: ScanForm | None = None,
        remember: bool = True,
        discover: DiscoverFn | None = None,
        session: SessionFn | None = None,
        process: ProcessFn | None = None,
    ) -> None:
        super().__init__()
        self._photos = PhotosModel(self)
        self._worker = Worker(self, discover=discover, session=session, process=process)
        start = form if form is not None else (load_form() if remember else ScanForm())
        self.controller = Controller(
            self._worker,
            start,
            save_form=save_form if remember else None,
            on_change=self._on_change,
        )
        self._close_signalled = False
        self._event.connect(self._dispatch, Qt.ConnectionType.QueuedConnection)

    # -- the worker's sink (called on the worker's thread) ----------------------------------

    def on_scanner(self, error: Exception | None) -> None:
        self._event.emit("on_scanner", error)

    def on_stage(self, stage: object) -> None:
        self._event.emit("on_stage", stage)

    def on_page(self, number: int) -> None:
        self._event.emit("on_page", number)

    def on_photo(self, files: object) -> None:
        self._event.emit("on_photo", files)

    def on_finished(self, result: object) -> None:
        self._event.emit("on_finished", result)

    def on_error(self, error: Exception) -> None:
        self._event.emit("on_error", error)

    @Slot(str, object)
    def _dispatch(self, name: str, payload: Any) -> None:
        getattr(self.controller, name)(payload)

    def _on_change(self) -> None:
        self._photos.set_items(self.controller.photos)
        self.changed.emit()
        if self.controller.close_ready and not self._close_signalled:
            self._close_signalled = True
            self.closeReady.emit()

    # -- what QML reads ---------------------------------------------------------------------

    @Property(str, notify=changed)
    def state(self) -> str:
        return self.controller.state.value

    @Property(str, notify=changed)
    def scannerText(self) -> str:
        return self.controller.scanner_text

    @Property(bool, notify=changed)
    def scannerOk(self) -> bool:
        return self.controller.scanner_ready

    @Property(str, notify=changed)
    def progressText(self) -> str:
        return self.controller.progress_text

    @Property(bool, notify=changed)
    def busy(self) -> bool:
        return self.controller.busy

    @Property(bool, notify=changed)
    def running(self) -> bool:
        return self.controller.running

    @Property(bool, notify=changed)
    def canScan(self) -> bool:
        return self.controller.can_scan

    @Property(bool, notify=changed)
    def canCancel(self) -> bool:
        return self.controller.can_cancel

    @Property(bool, notify=changed)
    def canCheck(self) -> bool:
        return self.controller.can_check

    @Property(bool, notify=changed)
    def canProcessKept(self) -> bool:
        return self.controller.can_process_kept

    @Property("QVariantMap", notify=changed)
    def form(self) -> dict[str, Any]:
        return asdict(self.controller.form)

    @Property("QVariantMap", notify=changed)
    def errors(self) -> dict[str, str]:
        return self.controller.errors

    @Property(str, notify=changed)
    def destination(self) -> str:
        return self.controller.destination or ""

    @Property(str, notify=changed)
    def bannerKind(self) -> str:
        banner = self.controller.banner
        return "" if banner is None else banner.kind

    @Property(str, notify=changed)
    def bannerText(self) -> str:
        banner = self.controller.banner
        return "" if banner is None else banner.text

    @Property(int, notify=changed)
    def photoCount(self) -> int:
        return len(self.controller.photos)

    @Property(str, notify=changed)
    def outputUrl(self) -> str:
        """The folder "Open folder" opens: where the photos went, else the output folder."""
        folder = self.controller.results_folder
        if folder is None and "output_folder" not in self.controller.errors:
            folder = Path(self.controller.form.output_folder.strip()).expanduser()
        return file_url(folder)

    @Property(QObject, constant=True)
    def photos(self) -> PhotosModel:
        return self._photos

    @Property("QVariantList", constant=True)
    def dpiChoices(self) -> list[int]:
        return list(SUPPORTED_DPI)

    @Property("QVariantList", constant=True)
    def feedChoices(self) -> list[str]:
        return list(FEED_CHOICES)

    @Property("QVariantList", constant=True)
    def backChoices(self) -> list[str]:
        return list(BACK_CHOICES)

    # -- what QML does ----------------------------------------------------------------------

    @Slot(str, "QVariant")
    def setField(self, name: str, value: Any) -> None:
        self.controller.set_field(name, value)

    @Slot(QUrl)
    def setOutputFolderUrl(self, url: QUrl) -> None:
        self.controller.set_field("output_folder", url.toLocalFile())

    @Slot()
    def checkScanner(self) -> None:
        self.controller.check_scanner()

    @Slot()
    def startScan(self) -> None:
        self.controller.start_scan()

    @Slot()
    def cancel(self) -> None:
        self.controller.cancel()

    @Slot()
    def processKept(self) -> None:
        self.controller.process_kept()

    @Slot(result=bool)
    def requestClose(self) -> bool:
        """True when the window may close now; otherwise a cancel is under way (closeReady)."""
        self._close_signalled = False
        return self.controller.request_close()

    # -- python side -------------------------------------------------------------------------

    def remember(self) -> None:
        """Save the form for the next run (the controller also does at every scan)."""
        try:
            save_form(self.controller.form)
        except OSError as error:
            logger.warning("could not remember the settings: %s", error)

    def shutdown(self) -> None:
        """Stop the running job, if any, and wait for it before the app goes away."""
        self._worker.cancel()
        self._worker.join(JOIN_TIMEOUT)
