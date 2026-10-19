"""The shared worker's recovery latch, backed by the durable scanner journal."""

from threading import Event

from fastfoto_linux.gui.power import RESTART_MESSAGE
from fastfoto_linux.scanner import recovery
from fastfoto_linux.scanner.power import PowerSettingsError
from fastfoto_linux.scanner.usb import UsbScanner


class PowerRecovery:
    def __init__(self) -> None:
        self.required = False
        self.scanner: UsbScanner | None = None
        self.error: Exception | None = None
        try:
            pending = recovery.pending_targets()
            self.required = bool(pending)
            self.scanner = pending[0] if pending else None
        except PowerSettingsError as error:
            self.observe(error)

    def observe(self, error: Exception) -> None:
        if getattr(error, "reconnect_required", False):
            self.required = True
            self.scanner = getattr(error, "scanner", None)
            self.error = error

    def require(self) -> None:
        if self.required:
            raise self._blocked()
        try:
            recovery.require_ready()
        except PowerSettingsError as error:
            self.observe(error)
            raise

    def check(self, visible: tuple[UsbScanner, ...], cancel: Event) -> UsbScanner:
        if cancel.is_set():
            raise self._blocked()
        try:
            restarted = recovery.check_reconnection(visible)
        except PowerSettingsError as error:
            self.observe(error)
            raise
        if restarted is None:
            original = self.scanner
            restarted = next(
                (
                    scanner
                    for scanner in visible
                    if original is not None
                    and scanner.sysfs_path == original.sysfs_path
                    and (scanner.bus, scanner.device) != (original.bus, original.device)
                ),
                None,
            )
        if restarted is None:
            raise self._blocked()
        self.required = False
        self.scanner = None
        self.error = None
        return restarted

    @property
    def message(self) -> str:
        detail = str(self.error) if self.error is not None else ""
        if RESTART_MESSAGE in detail:
            return detail
        return f"{detail} {RESTART_MESSAGE}" if detail else RESTART_MESSAGE

    def _blocked(self) -> PowerSettingsError:
        return PowerSettingsError(self.message, scanner=self.scanner, reconnect_required=True)
