"""Explicit USB reads and user-requested, verified changes to scanner power timers."""

import threading

from fastfoto_linux.scanner.errors import ScanCancelledError
from fastfoto_linux.scanner.libusb import open_scanner
from fastfoto_linux.scanner.maintenance import Maintenance
from fastfoto_linux.scanner.power_parse import parse_capabilities, parse_current
from fastfoto_linux.scanner.power_types import (
    PowerChanges,
    PowerCleanupError,
    PowerReadbackError,
    PowerSettingsError,
    PowerSnapshot,
    PowerWriteUncertainError,
    TimerCapability,
)
from fastfoto_linux.scanner.usb import UsbScanner, find_usb_scanners

__all__ = [
    "PowerChanges",
    "PowerCleanupError",
    "PowerReadbackError",
    "PowerSettingsError",
    "PowerSnapshot",
    "PowerWriteUncertainError",
    "TimerCapability",
    "apply_power_settings",
    "read_power_settings",
]


def read_power_settings(
    scanner: UsbScanner | None = None, *, cancel: threading.Event | None = None
) -> PowerSnapshot:
    """Read live USB maintenance capabilities and current values without changing timers."""
    return _run(_target(scanner, cancel), None, cancel)


def apply_power_settings(
    scanner: UsbScanner, changes: PowerChanges, *, cancel: threading.Event | None = None
) -> PowerSnapshot:
    """Validate against fresh device data, write once, then verify a fresh readback."""
    return _run(_target(scanner, cancel), changes, cancel)


def _target(scanner: UsbScanner | None, cancel: threading.Event | None) -> UsbScanner:
    if cancel is not None and cancel.is_set():
        raise ScanCancelledError("Reading scanner settings was cancelled.")
    if scanner is not None:
        return scanner
    scanners = find_usb_scanners()
    if not scanners:
        raise PowerSettingsError("No FF-680W found. Connect it by USB and switch it on.")
    if len(scanners) != 1:
        raise PowerSettingsError(
            "More than one FF-680W is connected. Connect only the intended scanner."
        )
    return scanners[0]


def _snapshot(session: Maintenance, scanner: UsbScanner) -> PowerSnapshot:
    capabilities = parse_capabilities(session.command(b"CAPA").payload)
    current = parse_current(session.command(b"RESA").payload, capabilities)
    return PowerSnapshot(scanner, *current, *capabilities)


def _apply(session: Maintenance, before: PowerSnapshot, changes: PowerChanges) -> PowerSnapshot:
    payload = _parameters(before, changes)
    if not payload:
        return before
    reply = session.command(b"PARA", payload)
    if reply.parameter_status != b"OK  ":
        raise PowerWriteUncertainError(
            "The scanner did not confirm the changes. Settings may have changed; refresh them.",
            scanner=before.scanner,
        )
    capabilities = (before.sleep_capability, before.power_off_capability)
    current = parse_current(session.command(b"RESA").payload, capabilities)
    after = PowerSnapshot(before.scanner, *current, *capabilities)
    expected = (changes.sleep_minutes, changes.power_off_minutes)
    if any(
        wanted is not None and wanted != got for wanted, got in zip(expected, current, strict=True)
    ):
        raise PowerReadbackError(
            "The scanner returned different settings after Apply. The current values are shown.",
            after,
        )
    return after


def _parameters(before: PowerSnapshot, changes: PowerChanges) -> bytes:
    fields = (
        (b"#SAV", changes.sleep_minutes, before.sleep_minutes, before.sleep_capability),
        (b"#POF", changes.power_off_minutes, before.power_off_minutes, before.power_off_capability),
    )
    payload = bytearray()
    for key, wanted, current, capability in fields:
        if wanted is None:
            continue
        if capability is None or current is None or not capability.accepts(wanted):
            raise PowerSettingsError(
                "The requested timer value is unavailable or outside its current limits."
            )
        if wanted != current:
            payload.extend(key + f"d{wanted:03d}".encode())
    return bytes(payload)


def _operation_error(
    error: Exception, session: Maintenance
) -> PowerSettingsError | ScanCancelledError:
    if session.parameter_attempted and not isinstance(error, PowerReadbackError):
        return PowerWriteUncertainError(
            "The changes could not be verified. Settings may have changed; "
            "refresh them before Apply.",
            scanner=session.scanner,
            reconnect_required=not session.synchronized,
        )
    if isinstance(error, ScanCancelledError) and session.synchronized:
        return error
    if isinstance(error, PowerSettingsError):
        error.scanner = session.scanner
        error.reconnect_required |= not session.synchronized
        return error
    return session.error(str(error))


def _run(
    scanner: UsbScanner, changes: PowerChanges | None, cancel: threading.Event | None
) -> PowerSnapshot:
    with open_scanner(scanner.bus, scanner.device) as transport:
        session = Maintenance(transport, scanner, cancel)
        error: Exception | None = None
        answer: PowerSnapshot | None = None
        try:
            session.acquire()
            answer = _snapshot(session, scanner)
            if changes is not None:
                answer = _apply(session, answer, changes)
        except (PowerSettingsError, ScanCancelledError) as exc:
            error = _operation_error(exc, session)
        finally:
            try:
                session.finish()
            except (PowerSettingsError, ScanCancelledError):
                if error is None:
                    error = PowerCleanupError(
                        "The settings session could not close cleanly. Restart the scanner.",
                        scanner=scanner,
                        reconnect_required=not session.synchronized,
                    )
                else:
                    error.add_note("The maintenance session also failed to close cleanly.")
                    if isinstance(error, PowerSettingsError):
                        error.reconnect_required |= not session.synchronized
                    else:
                        error = session.error(
                            f"{error} The maintenance session also failed to close cleanly."
                        )
        if error is not None:
            raise error
        assert answer is not None
        return answer
