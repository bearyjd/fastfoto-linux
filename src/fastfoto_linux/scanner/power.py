"""Explicit USB maintenance reads and writes for the scanner's power timers."""

import threading
from dataclasses import dataclass

from fastfoto_linux.scanner.errors import ScannerError
from fastfoto_linux.scanner.libusb import open_scanner  # noqa: F401 - injected transport seam
from fastfoto_linux.scanner.usb import UsbScanner, find_usb_scanners  # noqa: F401


@dataclass(frozen=True)
class TimerCapability:
    values: tuple[int, ...] = ()
    minimum: int | None = None
    maximum: int | None = None
    step: int = 1

    def accepts(self, value: int) -> bool:
        raise NotImplementedError


@dataclass(frozen=True)
class PowerSnapshot:
    scanner: UsbScanner
    sleep_minutes: int | None
    power_off_minutes: int | None
    sleep_capability: TimerCapability | None
    power_off_capability: TimerCapability | None


@dataclass(frozen=True)
class PowerChanges:
    sleep_minutes: int | None = None
    power_off_minutes: int | None = None


class PowerSettingsError(ScannerError):
    """Power settings could not be read or changed."""

    def __init__(
        self, message: str, *, scanner: UsbScanner | None = None, reconnect_required: bool = False
    ) -> None:
        super().__init__(message)
        self.scanner = scanner
        self.reconnect_required = reconnect_required


class PowerWriteUncertainError(PowerSettingsError):
    """The scanner may have changed settings; read them again before another Apply."""


class PowerReadbackError(PowerSettingsError):
    """The returned settings do not match the requested values."""

    def __init__(self, message: str, snapshot: PowerSnapshot) -> None:
        super().__init__(message, scanner=snapshot.scanner)
        self.snapshot = snapshot


class PowerCleanupError(PowerSettingsError):
    """The maintenance session could not be ended cleanly."""


def read_power_settings(
    scanner: UsbScanner | None = None, *, cancel: threading.Event | None = None
) -> PowerSnapshot:
    raise NotImplementedError


def apply_power_settings(
    scanner: UsbScanner, changes: PowerChanges, *, cancel: threading.Event | None = None
) -> PowerSnapshot:
    raise NotImplementedError
