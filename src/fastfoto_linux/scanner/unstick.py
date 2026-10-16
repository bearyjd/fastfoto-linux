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

from fastfoto_linux.scanner.errors import (
    NO_ANSWER_MESSAGE,
    ScanCancelledError,
    ScannerDisconnectedError,
    ScannerStuckError,
)

logger = logging.getLogger(__name__)

HELLO = b"\x1cX"  # FS X: a healthy scanner answers with a single ACK, in about no time
ACK = b"\x06"
FIN = b"FIN x0000000"  # ends a session; the 64-byte reply starts with these same bytes
FILLER_CHUNK = b" " * 64
MAX_FILLER_BYTES = 8 * 1024
HELLO_WAIT_S = 15.0  # a scanner has been seen to wake in over 12 s; a slow one gets no filler
FIN_WAIT_S = 2.0
READ_BYTES = 512
POLL_MS = 250  # one slice of a wait or of a send, so the longest a cancel waits to be noticed
DRAIN_WAIT_MS = 50
MAX_DRAIN_READS = 32
FILLER_REPLY_WAIT_MS = 300
OUT_BUDGET_S = 15.0  # how long a scanner may refuse an OUT (it is waking up) before it is "stuck"
RETRY_NAP_S = 0.001
SLOW_NOTICE_S = 2.0  # a check that takes longer than this tells the caller it is waiting

_sleep = time.sleep


class TransportError(Exception):
    """A USB transfer failed (not merely timed out)."""


class DeviceGoneError(TransportError):
    """The scanner is no longer on the bus (it may have restarted)."""


class UsbTransport(Protocol):
    """The scanner's bulk endpoints."""

    def write(self, data: bytes, timeout_ms: int) -> int:
        """Send ``data`` in one bulk OUT transfer of at most ``timeout_ms``; returns how many
        bytes went (a timeout is not an error: it may have taken some, or none)."""
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
        on_slow: Callable[[], None] | None,
    ) -> None:
        self._transport = transport
        self._cancel = cancel
        self._clock = clock
        self._on_slow = on_slow
        self._started = clock()

    def check_cancel(self) -> None:
        """Raise if the caller cancelled; the check also tells the caller once it runs long."""
        if self._cancel is not None and self._cancel.is_set():
            raise ScanCancelledError("scan cancelled while checking the scanner")
        if self._on_slow is not None and self._clock() - self._started >= SLOW_NOTICE_S:
            notify, self._on_slow = self._on_slow, None
            notify()

    def send(self, data: bytes) -> None:
        """Send all of data. A scanner that is waking up refuses an OUT for a while: the rest
        is offered again, in short slices, for up to OUT_BUDGET_S before it counts as stuck."""
        deadline = self._clock() + OUT_BUDGET_S
        rest = data
        while rest:
            self.check_cancel()
            rest = rest[self._write(rest) :]
            if rest and self._clock() >= deadline:
                logger.debug("the scanner took no more bytes for %g s", OUT_BUDGET_S)
                raise ScannerStuckError(NO_ANSWER_MESSAGE)

    def _write(self, data: bytes) -> int:
        try:
            return self._transport.write(data, POLL_MS)
        except DeviceGoneError as exc:
            raise ScannerDisconnectedError from exc
        except TransportError as exc:
            logger.debug("sending to the scanner failed: %s", exc)
            raise ScannerStuckError(NO_ANSWER_MESSAGE) from exc

    def read_once(self, timeout_ms: int) -> bytes:
        try:
            return self._transport.read(READ_BYTES, timeout_ms)
        except DeviceGoneError as exc:
            raise ScannerDisconnectedError from exc
        except TransportError as exc:
            logger.debug("reading from the scanner failed: %s", exc)
            raise ScannerStuckError(NO_ANSWER_MESSAGE) from exc

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
            self.check_cancel()
            if not self.read_once(DRAIN_WAIT_MS):
                return

    def hello(self) -> bytes | None:
        """Say hello and return the scanner's answer, None if it did not answer in time."""
        logger.debug("checking the scanner: hello")
        self.send(HELLO)
        return self.wait_reply(HELLO_WAIT_S)

    def finish(self) -> None:
        """End the session with FIN and read its reply, so that nothing is left in the pipe.

        The scanner has answered a hello by now, so a FIN that cannot be sent or answered does not
        stop the scan: only a cancel, or a scanner that has gone, does.
        """
        logger.debug("checking the scanner: FIN")
        try:
            self.send(FIN)
            reply = self.wait_reply(FIN_WAIT_S)
            if reply is None or not reply.startswith(FIN):
                logger.debug("the scanner did not answer the FIN as expected")
            self.drain()
        except ScannerStuckError:
            logger.debug("the session could not be ended with FIN; going on")

    def fill(self) -> int:
        """Pad out the command the scanner is waiting for, until it answers; returns the bytes."""
        sent = 0
        while sent < MAX_FILLER_BYTES:
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
    ``HELLO_WAIT_S`` gets nothing more unless ``allow_filler`` says the silence is the stuck
    session of our own failed send (it may as well be busy with another device, and filler would
    corrupt that); then it is sent filler in small chunks until it answers (at most
    ``MAX_FILLER_BYTES``), told to end the session, and greeted again to prove it is back.
    ``on_slow`` is called once if the check runs past ``SLOW_NOTICE_S``. Raises
    ScanCancelledError when ``cancel`` is set, ScannerDisconnectedError when the scanner is gone.
    """
    talk = _Conversation(transport, cancel, clock, on_slow)
    talk.drain()
    reply = talk.hello()
    if reply is not None and reply.startswith(ACK):
        talk.finish()
        return CheckResult(Outcome.HEALTHY)
    if reply is None and not allow_filler:
        logger.debug("the scanner is silent and there is no sign that it is stuck by us")
        raise ScannerStuckError(NO_ANSWER_MESSAGE)
    filler = talk.fill() if reply is None else 0
    talk.drain()
    talk.finish()
    talk.verify()
    if not filler:
        logger.debug("the scanner answered the hello with something else; ended the session")
        return CheckResult(Outcome.HEALTHY)
    logger.info("scanner was stuck; freed it (%d filler bytes sent)", filler)
    return CheckResult(Outcome.FREED, filler)
