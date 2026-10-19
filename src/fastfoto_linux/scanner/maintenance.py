"""Bounded ESC/I-2 maintenance exchanges with explicit ownership and frame alignment."""

import re
import threading
import time
from dataclasses import dataclass

from fastfoto_linux.scanner.errors import ScanCancelledError
from fastfoto_linux.scanner.power_parse import tokens
from fastfoto_linux.scanner.power_types import PowerSettingsError
from fastfoto_linux.scanner.unstick import TransportError, UsbTransport
from fastfoto_linux.scanner.usb import UsbScanner

OPERATION_TIMEOUT_S = 15.0
CLEANUP_TIMEOUT_S = 2.0
POLL_MS = 250
NO_PROGRESS_NAP_S = 0.001
HEADER_BYTES = 64
MAX_PAYLOAD_BYTES = 64 * 1024
_clock = time.monotonic
_sleep = time.sleep


@dataclass(frozen=True)
class Reply:
    payload: bytes
    parameter_status: bytes | None


class Maintenance:
    """Only a verified FS-Z ACK owns a session; only aligned frames may be finalized."""

    def __init__(
        self, transport: UsbTransport, scanner: UsbScanner, cancel: threading.Event | None
    ) -> None:
        self.transport, self.scanner, self.cancel = transport, scanner, cancel
        self.deadline = _clock() + OPERATION_TIMEOUT_S
        self.owned = False
        self.synchronized = True
        self.parameter_attempted = False
        self.cleaning_up = False

    def check(self) -> None:
        if not self.cleaning_up and self.cancel is not None and self.cancel.is_set():
            raise ScanCancelledError("Reading scanner settings was cancelled.")
        if _clock() >= self.deadline:
            raise self.error("The scanner settings operation timed out.")

    def error(self, message: str) -> PowerSettingsError:
        return PowerSettingsError(
            message, scanner=self.scanner, reconnect_required=not self.synchronized
        )

    def acquire(self) -> None:
        self.check()
        self.synchronized = False
        self._write(b"\x1cZ")
        if self._read(1) != b"\x06":
            raise self.error("The scanner did not grant access to its settings. It may be busy.")
        self.owned = self.synchronized = True

    def command(self, name: bytes, payload: bytes = b"") -> Reply:
        self.check()
        self.synchronized = False
        self.parameter_attempted |= name == b"PARA"
        self._write(name + f"x{len(payload):07X}".encode())
        if payload:
            self._write(payload)
        header = self._read(HEADER_BYTES)
        if header[:4] != name or not re.fullmatch(rb"x[0-9A-Fa-f]{7}", header[4:12]):
            raise self.error("The scanner returned an unexpected settings reply header.")
        length = int(header[5:12], 16)
        if length > MAX_PAYLOAD_BYTES:
            raise self.error("The scanner settings reply exceeds the supported size.")
        body = self._read(length)
        try:
            status = _statuses(header[12:])
        except PowerSettingsError as exc:
            raise self.error(str(exc)) from exc
        self.synchronized = True
        self.check()
        if status[0]:
            raise self.error("The scanner reported an error while accessing its settings.")
        if status[1] not in (None, b"NONE"):
            raise self.error("The scanner is busy or its settings are reserved. Try again later.")
        return Reply(body, status[2])

    def finish(self) -> None:
        if not self.owned or not self.synchronized:
            return
        self.cleaning_up = True
        self.deadline = _clock() + CLEANUP_TIMEOUT_S
        try:
            self.command(b"FIN ")
        except PowerSettingsError:
            # A rejected FIN leaves ownership/mode unresolved even if its frame was complete.
            self.synchronized = False
            raise
        self.owned = False

    def _timeout(self) -> int:
        self.check()
        return max(1, min(POLL_MS, int((self.deadline - _clock()) * 1000)))

    def _write(self, data: bytes) -> None:
        rest = data
        while rest:
            timeout = self._timeout()
            try:
                taken = self.transport.write(rest, timeout)
            except TransportError as exc:
                raise self.error(
                    "USB communication failed while sending scanner settings."
                ) from exc
            if not 0 <= taken <= len(rest):
                raise self.error("The scanner returned an invalid USB transfer length.")
            rest = rest[taken:]
            if taken == 0:
                _sleep(NO_PROGRESS_NAP_S)

    def _read(self, length: int) -> bytes:
        answer = bytearray()
        while len(answer) < length:
            timeout = self._timeout()
            try:
                data = self.transport.read(length - len(answer), timeout)
            except TransportError as exc:
                raise self.error(
                    "USB communication failed while reading scanner settings."
                ) from exc
            if len(data) > length - len(answer):
                raise self.error("The scanner returned too much USB data.")
            answer.extend(data)
            if not data:
                _sleep(NO_PROGRESS_NAP_S)
        return bytes(answer)


def _statuses(data: bytes) -> tuple[bool, bytes | None, bytes | None]:
    fields = list(tokens(data, require_terminator=True))
    error = False
    not_ready = parameter = None
    index = 0
    seen: set[bytes] = set()
    while index < len(fields):
        key = fields[index]
        index += 1
        if key not in (b"#err", b"#nrd", b"#par"):
            continue
        count = 2 if key == b"#err" else 1
        values = fields[index : index + count]
        if (
            key in seen
            or len(values) != count
            or any(type(v) is not bytes or v.startswith(b"#") for v in values)
        ):
            raise PowerSettingsError("The scanner returned an invalid settings reply status.")
        seen.add(key)
        index += count
        if key == b"#err":
            error = True
        elif key == b"#nrd":
            if values[0] not in (b"NONE", b"BUSY", b"WUP ", b"RSVD", b"AFEN"):
                raise PowerSettingsError("The scanner returned an unknown readiness status.")
            not_ready = values[0]
        else:
            if values[0] not in (b"OK  ", b"FAIL", b"LOST"):
                raise PowerSettingsError("The scanner returned an unknown parameter status.")
            parameter = values[0]
    return error, not_ready, parameter
