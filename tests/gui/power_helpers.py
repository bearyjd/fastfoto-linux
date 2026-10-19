"""Synthetic scanners and power replies; no USB access."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastfoto_linux.scanner.power import PowerSnapshot, TimerCapability
from fastfoto_linux.scanner.usb import UsbScanner

SCANNER = UsbScanner(1, 2, Path("/synthetic-usb/one"))
OTHER_SCANNER = UsbScanner(1, 3, Path("/synthetic-usb/two"))


def snapshot(**overrides: Any) -> PowerSnapshot:
    values = dict(
        scanner=SCANNER,
        sleep_minutes=17,
        power_off_minutes=60,
        sleep_capability=TimerCapability(minimum=1, maximum=240),
        power_off_capability=TimerCapability(values=(0, 30, 60, 120)),
    )
    return PowerSnapshot(**(values | overrides))


@dataclass
class PowerWorker:
    calls: list[tuple[str, object]] = field(default_factory=list)
    busy: bool = False

    def read_power(self, scanner: UsbScanner | None = None) -> None:
        self.calls.append(("read", scanner))

    def apply_power(self, scanner: UsbScanner, changes: object) -> None:
        self.calls.append(("apply", (scanner, changes)))
