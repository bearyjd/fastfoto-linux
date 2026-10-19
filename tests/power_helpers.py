"""Bounded scripted USB transports; never access a real scanner."""

import contextlib
from collections import deque
from collections.abc import Iterator
from pathlib import Path

import pytest

from fastfoto_linux.scanner import power
from fastfoto_linux.scanner.unstick import TransportError
from fastfoto_linux.scanner.usb import UsbScanner

TARGET = UsbScanner(1, 4, Path("/synthetic/usb"))
CAPS = b"#SAVRANGd001d240#POFLISTd000d030d060d120d240d480d720#---"
CURRENT = b"#SAVd010#POFd060#---"
UPDATED = b"#SAVd030#POFd000#---"


def frame(command: bytes, payload: bytes = b"", status: bytes = b"") -> bytes:
    return (command + f"x{len(payload):07X}".encode() + status + b"#---").ljust(
        64, b"\x00"
    ) + payload


class ScriptedUsb:
    def __init__(self, *replies: bytes | Exception, fragment: int = 64, partial: int = 65536):
        self.replies = deque(replies)
        self.sent: list[bytes] = []
        self.fragment, self.partial = fragment, partial
        self.released = False
        self.write_error_at: int | None = None
        self.writes = 0

    def write(self, data: bytes, timeout_ms: int) -> int:
        self.writes += 1
        if self.writes == self.write_error_at:
            raise TransportError("synthetic USB write failure")
        taken = min(len(data), self.partial)
        self.sent.append(data[:taken])
        return taken

    def read(self, size: int, timeout_ms: int) -> bytes:
        if not self.replies:
            raise TransportError("synthetic missing reply")
        reply = self.replies.popleft()
        if isinstance(reply, Exception):
            raise reply
        taken = min(len(reply), size, self.fragment)
        if taken < len(reply):
            self.replies.appendleft(reply[taken:])
        return reply[:taken]

    @property
    def stream(self) -> bytes:
        return b"".join(self.sent)


def install_usb(monkeypatch: pytest.MonkeyPatch, usb: ScriptedUsb) -> None:
    @contextlib.contextmanager
    def opened(bus: int, address: int) -> Iterator[ScriptedUsb]:
        assert (bus, address) == (TARGET.bus, TARGET.device)
        try:
            yield usb
        finally:
            usb.released = True

    monkeypatch.setattr(power, "open_scanner", opened)
    monkeypatch.setattr(power, "find_usb_scanners", lambda: (TARGET,))


def read_usb(**kwargs: int) -> ScriptedUsb:
    return ScriptedUsb(
        b"\x06", frame(b"CAPA", CAPS), frame(b"RESA", CURRENT), frame(b"FIN "), **kwargs
    )


def apply_usb(
    *, caps: bytes = CAPS, updated: bytes = UPDATED, status: bytes = b"#parOK  "
) -> ScriptedUsb:
    return ScriptedUsb(
        b"\x06",
        frame(b"CAPA", caps),
        frame(b"RESA", CURRENT),
        frame(b"PARA", status=status),
        frame(b"RESA", updated),
        frame(b"FIN "),
    )
