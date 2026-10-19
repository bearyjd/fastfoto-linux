"""Power settings drafts and the worker collaborators used by the settings page."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastfoto_linux.scanner.power import PowerSnapshot
from fastfoto_linux.scanner.usb import UsbScanner


@dataclass(frozen=True)
class PowerTools:
    """None selects the native backend; tests provide fake hardware functions."""

    read: Callable[..., PowerSnapshot] | None = None
    apply: Callable[..., PowerSnapshot] | None = None


@dataclass(frozen=True)
class PowerResult:
    snapshot: PowerSnapshot | None = None
    error: Exception | None = None


class PowerSettings:
    """A settings draft bound to the scanner returned by an explicit read."""

    def __init__(
        self, worker: Any, *, busy: Callable[[], bool], changed: Callable[[], None]
    ) -> None:
        self.snapshot: PowerSnapshot | None = None
        self.target: UsbScanner | None = None
        self.drafts: dict[str, int] = {}
        self.pending = False
        self.message = "Read settings to see the scanner's current power timers."

    @property
    def can_read(self) -> bool:
        raise NotImplementedError

    @property
    def can_apply(self) -> bool:
        raise NotImplementedError

    def read(self) -> None:
        raise NotImplementedError

    def apply(self) -> None:
        raise NotImplementedError

    def set_value(self, name: str, value: int) -> None:
        raise NotImplementedError

    def select(self, scanner: UsbScanner | None) -> None:
        raise NotImplementedError

    def complete(self, result: PowerResult) -> None:
        raise NotImplementedError
