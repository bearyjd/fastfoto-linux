"""Durable per-enumeration maintenance recovery guards."""

from pathlib import Path

from fastfoto_linux.scanner.usb import UsbScanner


def marker_path(scanner: UsbScanner) -> Path:
    raise NotImplementedError


def pending_targets() -> tuple[UsbScanner, ...]:
    raise NotImplementedError


def require_ready(scanner: UsbScanner | None = None) -> None:
    raise NotImplementedError


def require_address_ready(bus: int, address: int) -> None:
    raise NotImplementedError


def begin(scanner: UsbScanner) -> None:
    raise NotImplementedError


def complete(scanner: UsbScanner) -> None:
    raise NotImplementedError


def check_reconnection(scanners: tuple[UsbScanner, ...] | None = None) -> UsbScanner | None:
    raise NotImplementedError
