"""The object QML talks to: the controller's properties and slots, on the GUI thread."""

import functools
import html
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QObject, Qt, QUrl, Signal, Slot

from fastfoto_linux.gui.controller import Controller
from fastfoto_linux.gui.form import BACK_CHOICES, FEED_CHOICES, ScanForm, absolute_folder
from fastfoto_linux.gui.prefs import load_form, save_form
from fastfoto_linux.gui.qt.photos_model import PhotosModel, file_url
from fastfoto_linux.gui.state import ActionBlockedError
from fastfoto_linux.gui.worker import DiscoverFn, ProcessFn, SessionFn, Worker
from fastfoto_linux.scanner import SUPPORTED_DPI

logger = logging.getLogger(__name__)

SHUTDOWN_WAIT = 10.0  # seconds to wait for a cancelled job to wind down on shutdown
SHUTDOWN_SLICE = 0.1  # the wait is made of short joins, so an abort is noticed
ABORT_GRACE = 1.0  # after an abort: just long enough for the job to stop scanimage
PRESERVE_SPACES = "white-space:pre-wrap"


def rich_text(text: str) -> str:
    """``text`` for a Kirigami message, which shows what looks like markup as markup.

    InlineMessage has no ``textFormat``; its label guesses (AutoText). Escaping the text and
    wrapping it in a tag makes the guess "rich text", in which the escapes show the text as it is
    (and ``pre-wrap`` keeps the text's own spacing and line breaks).
    """
    return (
        f'<span style="{PRESERVE_SPACES}">{html.escape(text, quote=False)}</span>' if text else ""
    )


def _guarded[**P, R](
    default: R, *, job: bool = False
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """A slot that never raises: QML would print the traceback and leave the page looking dead.

    A refused action (``ActionBlockedError``) changes nothing: the page is only told, so a button
    that looked enabled is redrawn. Anything unexpected becomes a banner, and the FAILED state
    unless a healthy job is running; ``job`` marks the slot that handles the job's own reports,
    whose failure stops the job, so a page cannot stay stuck in SCANNING or CANCELLING.
    """

    def decorate(method: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(method)
        def guarded(*args: P.args, **kwargs: P.kwargs) -> R:
            bridge: Any = args[0]
            try:
                return method(*args, **kwargs)
            except ActionBlockedError as blocked:
                logger.info("refused: %s", blocked)
                bridge.changed.emit()
                return default
            except Exception as error:
                bridge._fail(error, job=job)
                return default

        return guarded

    return decorate


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
        self._closed = False
        self._shut_down = False
        self._aborted = threading.Event()
        self._event.connect(self._dispatch, Qt.ConnectionType.QueuedConnection)

    # -- the worker's sink (called on the worker's thread) ----------------------------------

    def on_scanner(self, error: Exception | None) -> None:
        self._send("on_scanner", error)

    def on_stage(self, stage: object) -> None:
        self._send("on_stage", stage)

    def on_page(self, number: int) -> None:
        self._send("on_page", number)

    def on_photo(self, files: object) -> None:
        self._send("on_photo", files)

    def on_finished(self, result: object) -> None:
        self._send("on_finished", result)

    def on_error(self, error: Exception) -> None:
        self._send("on_error", error)

    def _send(self, name: str, payload: object) -> None:
        """Hand an event to the GUI thread, unless the window is gone (the job may outlive it)."""
        if self._closed:
            return
        try:
            self._event.emit(name, payload)
        except RuntimeError:  # the Qt object was deleted under a worker still reporting
            self._closed = True

    @Slot(str, object)
    @_guarded(None, job=True)
    def _dispatch(self, name: str, payload: Any) -> None:
        getattr(self.controller, name)(payload)

    def _fail(self, error: Exception, *, job: bool = False) -> None:
        try:
            self.controller.fail(error, job=job)
        except Exception:
            logger.exception("could not show the error %r", error)

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

    @Property(str, notify=changed)
    def bannerHtml(self) -> str:
        """``bannerText`` made safe for Kirigami's InlineMessage (see ``rich_text``)."""
        return rich_text(self.bannerText)

    @Property(str, notify=changed)
    def keptHtml(self) -> str:
        """What the offer to process the pages a cancel kept says (empty when there is none)."""
        return rich_text(self.controller.kept_text)

    @Property(str, notify=changed)
    def whyNotScan(self) -> str:
        """Why the Scan button is disabled, in words; empty when it is enabled."""
        return self.controller.scan_blocker

    @Property(str, notify=changed)
    def processKeptText(self) -> str:
        """What the button that processes the pages a cancel kept says."""
        return self.controller.process_kept_text

    @Property(str, notify=changed)
    def closeTitle(self) -> str:
        return self.controller.close_title

    @Property(str, notify=changed)
    def closeText(self) -> str:
        return self.controller.close_text

    @Property(int, notify=changed)
    def photoCount(self) -> int:
        return len(self.controller.photos)

    @Property(str, notify=changed)
    def outputUrl(self) -> str:
        """The folder "Open folder" opens: where the photos went, else the output folder."""
        folder = self.controller.results_folder
        if folder is None and "output_folder" not in self.controller.errors:
            typed = absolute_folder(self.controller.form.output_folder)
            folder = Path(typed) if typed else None
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
    @_guarded(None)
    def setField(self, name: str, value: Any) -> None:
        self.controller.set_field(name, value)

    @Slot()
    @_guarded(None)
    def checkDisk(self) -> None:
        """The user left the folder or album field: look at the disk now."""
        self.controller.check_disk()

    @Slot(QUrl)
    @_guarded(None)
    def setOutputFolderUrl(self, url: QUrl) -> None:
        self.controller.set_field("output_folder", url.toLocalFile())
        self.controller.check_disk()

    @Slot()
    @_guarded(None)
    def checkScanner(self) -> None:
        self.controller.check_scanner()

    @Slot()
    @_guarded(None)
    def startScan(self) -> None:
        self.controller.start_scan()

    @Slot()
    @_guarded(None)
    def cancel(self) -> None:
        self.controller.cancel()

    @Slot()
    @_guarded(None)
    def processKept(self) -> None:
        self.controller.process_kept()

    @Slot(result=bool)
    @_guarded(True)
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

    def abort(self) -> None:
        """Stop waiting for the job (a second signal): cancel it and let ``shutdown`` end soon.

        Safe to call from any thread.
        """
        self._worker.cancel()
        self._aborted.set()

    def shutdown(self) -> None:
        """Stop the running job, if any, and wait for it (a while) before the app goes away.

        From here on the bridge ignores what the job reports: the window is going. The wait is
        bounded by ``SHUTDOWN_WAIT`` and ends after a short grace when ``abort`` is called. A
        second call returns at once.
        """
        if self._shut_down:
            return
        self._shut_down = True
        self._closed = True
        self._worker.cancel()
        deadline = time.monotonic() + SHUTDOWN_WAIT
        while self._worker.alive and time.monotonic() < deadline:
            if self._aborted.is_set():
                self._worker.join(ABORT_GRACE)  # time for the job to stop scanimage
                return
            self._worker.join(SHUTDOWN_SLICE)
