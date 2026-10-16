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

from fastfoto_linux.gui.controller import Controller, disk_key
from fastfoto_linux.gui.form import (
    BACK_CHOICES,
    FEED_CHOICES,
    ScanForm,
    absolute_folder,
    validate_filesystem,
)
from fastfoto_linux.gui.prefs import load_form, save_form
from fastfoto_linux.gui.qt.photos_model import PhotosModel, file_url
from fastfoto_linux.gui.state import ActionBlockedError
from fastfoto_linux.gui.worker import DiscoverFn, ProcessFn, SessionFn, Worker
from fastfoto_linux.scanner import SUPPORTED_DPI
from fastfoto_linux.scanner.run import TERMINATE_GRACE_S

logger = logging.getLogger(__name__)

# On top of the Cancel grace: a job that is cancelled starts the grace when it notices (up to a
# poll later) and the SIGKILL, the reaping and the settling of the pages come after it.
SHUTDOWN_MARGIN_S = 3.0
# How long to wait for a cancelled job to wind down on shutdown. Longer than the grace scanimage is
# given to stop the scanner, so the SIGKILL of one that ignores SIGTERM happens before the app
# gives up (it would otherwise leave an orphan scanimage holding the scanner).
SHUTDOWN_WAIT = TERMINATE_GRACE_S + SHUTDOWN_MARGIN_S
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
    _disk = Signal(object, object)

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
            disk_check=self._start_disk_check,
        )
        self._close_signalled = False
        self._closed = False
        # Guards ``_closed`` and every emit from a thread. Not re-entrant, on purpose: that is safe
        # because ``_event`` and ``_disk`` are private signals with queued connections only, so an
        # emit just posts an event and runs no slot while the lock is held. Never connect a slot
        # to either of them directly (a direct slot that emitted again would deadlock here).
        self._emit_lock = threading.Lock()
        self._shut_down = False
        self._aborted = False  # a plain flag, see ``give_up_waiting``
        self._event.connect(self._dispatch, Qt.ConnectionType.QueuedConnection)
        self._disk.connect(self._disk_answered, Qt.ConnectionType.QueuedConnection)
        self.checkDisk()  # the folder of the remembered form, looked at off the GUI thread

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
        self._emit(self._event, name, payload)

    def _emit(self, signal: Any, *args: object) -> None:
        """Hand an event to the GUI thread, unless the window is gone (the job may outlive it).

        The check and the emit are one step under ``_emit_lock``, which ``_close_events`` takes too:
        once that has returned, no thread is inside an emit, so the bridge may be deleted. (The
        signals are queued, so the emit only posts an event and the lock is held for a moment.)
        """
        with self._emit_lock:
            if self._closed:
                return
            try:
                signal.emit(*args)
            except RuntimeError:  # the Qt object was deleted under a worker still reporting
                self._closed = True

    def _close_events(self) -> None:
        """Stop handing events to the GUI thread; returns once no thread is in the middle of one."""
        with self._emit_lock:
            self._closed = True

    def _start_disk_check(self, form: ScanForm) -> None:
        """Look at the disk for ``form`` on a thread of its own and return at once."""
        threading.Thread(
            target=self._read_disk, args=(form,), name="fastfoto-disk", daemon=True
        ).start()

    def _read_disk(self, form: ScanForm) -> None:
        """On a thread of its own: a hung network mount may take a long while to answer."""
        try:
            errors = validate_filesystem(form)
        except Exception as error:
            logger.exception("could not look at the folder")
            errors = {"output_folder": f"Could not look at the folder: {error}"}
        self._emit(self._disk, disk_key(form), errors)

    @Slot(object, object)
    @_guarded(None)
    def _disk_answered(self, key: Any, errors: Any) -> None:
        self.controller.on_disk(key, errors)

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
    def startingScan(self) -> bool:
        """True while the folder is looked at before a scan starts (Cancel gives that up)."""
        return self.controller.starting_scan

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
    def processKeptFolder(self) -> str:
        """The folder those pages go to: QML shows it as plain text beside the button."""
        return self.controller.process_kept_folder

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

    @property
    def job_alive(self) -> bool:
        """True while the job's thread is still running (it may have been cancelled already)."""
        return self._worker.alive

    def abort(self) -> None:
        """Stop waiting for the job (a second signal): cancel it and let ``shutdown`` end soon.

        Safe to call from any thread, but not from a signal handler: use ``give_up_waiting``.
        """
        self._worker.cancel()
        self.give_up_waiting()

    def give_up_waiting(self) -> None:
        """Make ``shutdown`` stop waiting for the job. It only assigns a plain flag, which a signal
        handler may do: the handler runs between two instructions of the thread it interrupts, so
        it must not take a lock (``Event.set`` does) that this thread could be holding."""
        self._aborted = True

    def shutdown(self) -> None:
        """Stop the running job, if any, and wait for it (a while) before the app goes away.

        From here on the bridge ignores what the job reports: the window is going. The wait is
        bounded by ``SHUTDOWN_WAIT`` and ends after a short grace when ``abort`` is called. A
        second call returns at once.
        """
        if self._shut_down:
            return
        self._shut_down = True
        self._close_events()
        self._worker.cancel()
        deadline = time.monotonic() + SHUTDOWN_WAIT
        while self._worker.alive and time.monotonic() < deadline:
            if self._aborted:
                self._worker.join(ABORT_GRACE)  # time for the job to stop scanimage
                return
            self._worker.join(SHUTDOWN_SLICE)
