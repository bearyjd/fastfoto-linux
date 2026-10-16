"""Check that the FF-680W answers before a scan, and free it when a failed send has jammed it.

The scanner's command channel can be left half-way through a command: a send that failed after
the scanner took only part of its payload makes it swallow every later byte while it waits for
the rest. This module is the protocol only; it talks to the scanner through a ``UsbTransport``
so that it can be tested with a fake, and the libusb binding lives in ``libusb``.
"""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum, auto
from typing import Protocol

HELLO = b"\x1cX"  # FS X: the scanner answers with a single ACK when it is healthy
ACK = b"\x06"
FIN = b"FIN x0000000"  # ends a session; the 64-byte reply starts with these same bytes
FILLER_CHUNK = b" " * 64
MAX_FILLER_BYTES = 8 * 1024
HELLO_WAIT_S = 5.0  # a merely slow scanner must never be sent filler
FIN_WAIT_S = 2.0
READ_BYTES = 512
POLL_MS = 250  # one slice of a wait, and so the longest a cancel waits to be noticed
DRAIN_WAIT_MS = 50
MAX_DRAIN_READS = 32
FILLER_REPLY_WAIT_MS = 300


class TransportError(Exception):
    """A USB transfer failed (not merely timed out)."""


class UsbTransport(Protocol):
    """The scanner's bulk endpoints."""

    def write(self, data: bytes) -> None:
        """Send ``data`` in one bulk OUT transfer; TransportError if it did not all go."""
        ...

    def read(self, size: int, timeout_ms: int) -> bytes:
        """Up to ``size`` bytes from the bulk IN endpoint; empty if nothing came in time."""
        ...


class Outcome(StrEnum):
    HEALTHY = auto()  # it answered at once
    FREED = auto()  # it was stuck and answers again


@dataclass(frozen=True)
class CheckResult:
    outcome: Outcome
    filler_bytes: int = 0


def ensure_ready(
    transport: UsbTransport,
    *,
    cancel: threading.Event | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> CheckResult:
    """Make sure the scanner answers a hello; raises ScannerStuckError if it cannot be freed.

    Raises ScanCancelledError when ``cancel`` is set while waiting.
    """
    raise NotImplementedError
