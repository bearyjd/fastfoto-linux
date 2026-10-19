"""Immutable power settings and explicit maintenance failure information."""

from dataclasses import dataclass

from fastfoto_linux.scanner.errors import ScannerError
from fastfoto_linux.scanner.usb import UsbScanner

MAX_TIMER_MINUTES = 999


@dataclass(frozen=True)
class TimerCapability:
    values: tuple[int, ...] = ()
    minimum: int | None = None
    maximum: int | None = None
    step: int = 1

    def accepts(self, value: int) -> bool:
        if type(value) is not int or not 0 <= value <= MAX_TIMER_MINUTES:
            return False
        if self.values:
            return value in self.values
        return (
            self.minimum is not None
            and self.maximum is not None
            and self.step > 0
            and self.minimum <= value <= self.maximum
            and (value - self.minimum) % self.step == 0
        )


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
