"""Power settings drafts and the worker collaborators used by the settings page."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from fastfoto_linux.gui.state import ActionBlockedError
from fastfoto_linux.scanner import ScannerNotFoundError
from fastfoto_linux.scanner.power import PowerChanges, PowerSnapshot, TimerCapability
from fastfoto_linux.scanner.usb import UsbScanner

RESTART_MESSAGE = (
    "Turn the scanner off and on before continuing. "
    "Then choose Check USB reconnection before reading settings or scanning again."
)
TIMER_FIELDS = ("sleep_minutes", "power_off_minutes")


@dataclass(frozen=True)
class PowerTools:
    """None selects the native backend; tests provide fake hardware functions."""

    read: Callable[..., PowerSnapshot] | None = None
    apply: Callable[..., PowerSnapshot] | None = None
    discover: Callable[[], tuple[UsbScanner, ...]] | None = None


@dataclass(frozen=True)
class PowerResult:
    snapshot: PowerSnapshot | None = None
    error: Exception | None = None
    recovered_scanner: UsbScanner | None = None


class PowerPort(Protocol):
    def read_power(self, scanner: UsbScanner | None = None) -> None: ...
    def apply_power(self, scanner: UsbScanner, changes: PowerChanges) -> None: ...
    def check_power_connection(self) -> None: ...


class PowerSettings:
    """A settings draft bound to the scanner returned by an explicit read."""

    def __init__(
        self, worker: PowerPort, *, busy: Callable[[], bool], changed: Callable[[], None]
    ) -> None:
        self._worker = worker
        self._busy = busy
        self._changed = changed
        self._operation = ""
        self._requires_reconnect = False
        self.snapshot: PowerSnapshot | None = None
        self.target: UsbScanner | None = None
        self.drafts: dict[str, int] = {}
        self.pending = False
        self.message = (
            self.recovery_message
            if self.reconnect_required
            else "Read settings to see the scanner's current power timers."
        )

    @property
    def reconnect_required(self) -> bool:
        return self._requires_reconnect or bool(getattr(self._worker, "reconnect_required", False))

    @property
    def recovery_message(self) -> str:
        return getattr(self._worker, "power_recovery_message", RESTART_MESSAGE)

    @property
    def available(self) -> bool:
        return not self.pending and not self._busy()

    @property
    def can_read(self) -> bool:
        return self.available and not self.reconnect_required

    @property
    def can_apply(self) -> bool:
        return (
            self.can_read
            and self.snapshot is not None
            and bool(self._changes())
            and all(
                (capability := self.capability(name)) is not None and capability.accepts(value)
                for name, value in self.drafts.items()
            )
        )

    def capability(self, name: str) -> TimerCapability | None:
        if self.snapshot is None:
            return None
        if name == "sleep_minutes":
            return self.snapshot.sleep_capability
        if name == "power_off_minutes":
            return self.snapshot.power_off_capability
        raise ValueError("Unknown power setting")

    def read(self) -> None:
        if not self.can_read:
            raise ActionBlockedError(self.message or "Wait for the current job before reading.")
        self._start("read", lambda: self._worker.read_power(self.target))

    def apply(self) -> None:
        if not self.can_apply or self.target is None:
            raise ActionBlockedError("Read settings and choose a supported changed value first.")
        changes = PowerChanges(**self._changes())
        self._start("apply", lambda: self._worker.apply_power(self.target, changes))

    def set_value(self, name: str, value: int) -> None:
        if not self.can_read or name not in self.drafts:
            raise ActionBlockedError("This power setting is unavailable for editing.")
        self.drafts = self.drafts | {name: value}
        self._changed()

    def select(self, scanner: UsbScanner | None) -> None:
        self.target = scanner
        self.snapshot = None
        self.drafts = {}
        self.pending = False
        self._operation = ""
        self.message = (
            self.recovery_message if self.reconnect_required else "Read settings for this scanner."
        )
        self._changed()

    def complete(self, result: PowerResult) -> None:
        if not self.pending:
            if result.error is not None and getattr(result.error, "reconnect_required", False):
                self._requires_reconnect = True
                self.snapshot = None
                self.drafts = {}
                self.message = self._reconnect_message(result.error)
                self._changed()
            return
        operation = self._operation
        self.pending = False
        self._operation = ""
        self.snapshot = None
        self.drafts = {}
        if result.error is not None:
            self._requires_reconnect |= bool(getattr(result.error, "reconnect_required", False))
            self.message = str(result.error)
            if isinstance(result.error, ScannerNotFoundError):
                self.target = None
            reported = getattr(result.error, "snapshot", None)
            if isinstance(reported, PowerSnapshot) and reported.scanner == self.target:
                self.snapshot = reported
            if self.reconnect_required:
                self.message = self._reconnect_message(result.error)
        elif result.recovered_scanner is not None:
            self._requires_reconnect = False
            self.target = result.recovered_scanner
            self.message = "USB reconnection found. Read settings again before applying changes."
        elif result.snapshot is not None:
            self._accept(result.snapshot, operation)
        else:
            self.message = "No power settings were returned. Read settings again."
        self._changed()

    def check_connection(self) -> None:
        if not self.available or not self.reconnect_required:
            raise ActionBlockedError("A USB reconnection check is not available now.")
        self._start("reconnect", self._worker.check_power_connection)

    def _changes(self) -> dict[str, int]:
        if self.snapshot is None:
            return {}
        return {
            name: value
            for name, value in self.drafts.items()
            if value != getattr(self.snapshot, name)
        }

    def _start(self, operation: str, action: Callable[[], None]) -> None:
        self.pending = True
        self._operation = operation
        self.message = "Applying power settings…" if operation == "apply" else "Reading settings…"
        if operation == "reconnect":
            self.message = "Checking USB reconnection…"
        try:
            action()
        except Exception as error:
            self.complete(PowerResult(error=error))
        self._changed()

    def _accept(self, snapshot: PowerSnapshot, operation: str) -> None:
        if self.target is not None and snapshot.scanner != self.target:
            self.message = (
                "The scanner changed. Select the intended scanner and read settings again."
            )
            return
        self.snapshot = snapshot
        self.target = snapshot.scanner
        self.drafts = {
            name: value
            for name in TIMER_FIELDS
            if self.capability(name) is not None and (value := getattr(snapshot, name)) is not None
        }
        self.message = (
            "Changes applied and verified on the scanner."
            if operation == "apply"
            else "Current settings read from the scanner. Edit a draft, then choose Apply changes."
        )

    @staticmethod
    def _reconnect_message(error: Exception) -> str:
        message = str(error)
        return message if RESTART_MESSAGE in message else f"{message} {RESTART_MESSAGE}"
