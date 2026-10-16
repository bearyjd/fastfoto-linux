"""Check that the FF-680W answers before a scan, and free it when a failed send has jammed it.

The scanner's command channel can be left half-way through a command: a send that failed after
the scanner took only part of its payload makes it swallow every later byte while it waits for
the rest. Padding the missing bytes out makes it answer (with a parameter failure) and go back to
normal, with no reset. This module is the protocol only; it talks to the scanner through a
``UsbTransport`` so that it can be tested with a fake, and the libusb binding lives in ``libusb``.

Only command names and byte counts are ever logged, never the bytes themselves.
"""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum, auto
from typing import Protocol

from fastfoto_linux.scanner.errors import ScanCancelledError, ScannerStuckError

logger = logging.getLogger(__name__)

HELLO = b"\x1cX"  # FS X: a healthy scanner answers with a single ACK, in about no time
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
OUT_BUDGET_S = 15.0  # how long a scanner may refuse an OUT (it is waking up) before it is "stuck"
SLOW_NOTICE_S = 2.0  # a check that takes longer than this tells the caller it is waiting


class TransportError(Exception):
    """A USB transfer failed (not merely timed out)."""


class DeviceGoneError(TransportError):
    """The scanner is no longer on the bus (it may have restarted)."""


class UsbTransport(Protocol):
    """The scanner's bulk endpoints."""

    def write(self, data: bytes, timeout_ms: int = POLL_MS) -> int:
        """Send ``data`` in one bulk OUT transfer; returns how many bytes went."""
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


class _Conversation:
    """One check's side of the exchange: sends, waits, drains, and honours the cancel event."""

    def __init__(
        self,
        transport: UsbTransport,
        cancel: threading.Event | None,
        clock: Callable[[], float],
    ) -> None:
        self._transport = transport
        self._cancel = cancel
        self._clock = clock

    def check_cancel(self) -> None:
        if self._cancel is not None and self._cancel.is_set():
            raise ScanCancelledError("scan cancelled while checking the scanner")

    def send(self, data: bytes) -> None:
        try:
            self._transport.write(data)
        except TransportError as exc:
            logger.debug("sending to the scanner failed: %s", exc)
            raise ScannerStuckError from exc

    def read_once(self, timeout_ms: int) -> bytes:
        try:
            return self._transport.read(READ_BYTES, timeout_ms)
        except TransportError as exc:
            logger.debug("reading from the scanner failed: %s", exc)
            raise ScannerStuckError from exc

    def wait_reply(self, wait_s: float) -> bytes | None:
        """The next bytes the scanner says within ``wait_s`` seconds, None if it stays silent."""
        deadline = self._clock() + wait_s
        while True:
            self.check_cancel()
            data = self.read_once(POLL_MS)
            if data:
                return data
            if self._clock() >= deadline:
                return None

    def drain(self) -> None:
        """Throw away what is waiting to be read, so that an old reply is not taken for a new."""
        for _ in range(MAX_DRAIN_READS):
            if not self.read_once(DRAIN_WAIT_MS):
                return

    def hello(self) -> bytes | None:
        """Say hello and return the scanner's answer, None if it did not answer in time."""
        logger.debug("checking the scanner: hello")
        self.send(HELLO)
        return self.wait_reply(HELLO_WAIT_S)

    def finish(self) -> None:
        """End the session with FIN and read its reply, so that nothing is left in the pipe."""
        logger.debug("checking the scanner: FIN")
        self.send(FIN)
        reply = self.wait_reply(FIN_WAIT_S)
        if reply is None or not reply.startswith(FIN):
            logger.debug("the scanner did not answer the FIN as expected")
        self.drain()

    def fill(self) -> int:
        """Pad out the command the scanner is waiting for, until it answers; returns the bytes."""
        sent = 0
        while sent < MAX_FILLER_BYTES:
            self.check_cancel()
            self.send(FILLER_CHUNK)
            sent += len(FILLER_CHUNK)
            if self.read_once(FILLER_REPLY_WAIT_MS):
                logger.debug("the scanner answered after %d filler bytes", sent)
                return sent
        logger.debug("the scanner did not answer %d filler bytes", sent)
        raise ScannerStuckError

    def verify(self) -> None:
        """Hello must now be answered with an ACK, or the scanner is not free after all."""
        reply = self.hello()
        if reply is None or not reply.startswith(ACK):
            raise ScannerStuckError
        self.finish()


def ensure_ready(
    transport: UsbTransport,
    *,
    cancel: threading.Event | None = None,
    clock: Callable[[], float] = time.monotonic,
    allow_filler: bool = False,
    on_slow: Callable[[], None] | None = None,
) -> CheckResult:
    """Make sure the scanner answers a hello; raises ScannerStuckError if it cannot be freed.

    A healthy scanner is greeted and told to end the session. One that is silent for
    ``HELLO_WAIT_S`` is sent filler in small chunks until it answers (at most
    ``MAX_FILLER_BYTES``), then told to end the session, and greeted again to prove it is back.
    Raises ScanCancelledError when ``cancel`` is set while waiting.
    """
    talk = _Conversation(transport, cancel, clock)
    talk.drain()
    reply = talk.hello()
    if reply is not None and reply.startswith(ACK):
        talk.finish()
        return CheckResult(Outcome.HEALTHY)
    filler = talk.fill() if reply is None else 0
    talk.drain()
    talk.finish()
    talk.verify()
    logger.info("scanner was stuck; freed it (%d filler bytes sent)", filler)
    return CheckResult(Outcome.FREED, filler)
