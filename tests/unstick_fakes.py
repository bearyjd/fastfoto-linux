"""A fake scanner behind ``UsbTransport`` and a clock it drives, for the pre-scan check tests."""

import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

from fastfoto_linux.scanner import unstick
from fastfoto_linux.scanner.unstick import TransportError

PARA_FAIL = b"PARAx0000000#parFAIL#" + b"-" * 43
FIN_REPLY = b"FIN x0000000#" + b"-" * 51
OLD_WRITE_TIMEOUT_MS = 1000  # what a check that does not choose its slices gets
STUCK_NEEDS_BYTES = 832  # what the real scanner swallowed before it answered (hardware session)


class FakeClock:
    """Time only moves when the fake scanner is waited on, so no test sleeps."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@dataclass
class FakeScanner:
    """Plays the scanner's side of the check.

    ``swallow`` is how many bytes a stuck scanner takes before it answers with a parameter
    failure (``None``: it never answers, i.e. dead). ``reply_after_s`` delays the answer to a
    hello (a slow but healthy scanner). ``recovers`` says whether it works again after the
    parameter failure. ``hello_reply`` replaces the first answer to a hello.

    A scanner that is waking up refuses bulk OUTs: ``refuse_out_until_s`` is the time before
    which every OUT takes nothing (and lasts its whole timeout), ``refuse_only`` limits that to
    one command, and ``accept_per_call`` makes every OUT take at most that many bytes.
    ``writes`` lists what each OUT took; ``stream`` is all of it joined. ``write_timeouts``
    are the timeouts the check asked for; ``write_error`` is raised by every OUT, or only by the
    OUT of ``error_on``.
    """

    clock: FakeClock
    swallow: int | None = 0
    reply_after_s: float = 0.0
    recovers: bool = True
    hello_reply: bytes | None = None
    stale: tuple[bytes, ...] = ()
    after_fin: tuple[bytes, ...] = ()
    fail_writes: bool = False
    write_error: TransportError | None = None
    error_on: bytes | None = None
    read_error: TransportError | None = None
    refuse_out_until_s: float = 0.0
    refuse_only: bytes | None = None
    accept_per_call: int | None = None
    on_read: "Callable[[FakeScanner], None] | None" = None
    on_write: "Callable[[FakeScanner], None] | None" = None
    writes: list[bytes] = field(default_factory=list)
    write_timeouts: list[int] = field(default_factory=list)
    write_attempts: int = 0
    reads: int = 0
    _ready: deque[tuple[float, bytes]] = field(default_factory=deque)
    _inbox: bytes = b""
    _swallowed: int = 0
    _stuck: bool = False
    _dead: bool = False

    def __post_init__(self) -> None:
        self._stuck = self.swallow != 0
        self._ready.extend((0.0, data) for data in self.stale)

    def write(self, data: bytes, timeout_ms: int = OLD_WRITE_TIMEOUT_MS) -> int:
        self.write_attempts += 1
        self.write_timeouts.append(timeout_ms)
        if self.on_write is not None:
            self.on_write(self)
        if self.fail_writes:
            raise TransportError("bulk OUT failed")
        if self.write_error is not None and self.error_on in (None, data):
            raise self.write_error
        if self._refuses(data):
            self.clock.now += timeout_ms / 1000  # the transfer ran out its whole timeout
            return 0
        taken = data if self.accept_per_call is None else data[: self.accept_per_call]
        self.writes.append(taken)
        self._take(taken)
        return len(taken)

    def read(self, size: int, timeout_ms: int) -> bytes:
        self.reads += 1
        if self.on_read is not None:
            self.on_read(self)
        if self.read_error is not None:
            raise self.read_error
        deadline = self.clock.now + timeout_ms / 1000
        if self._ready and self._ready[0][0] <= deadline:
            ready_at, data = self._ready.popleft()
            self.clock.now = max(self.clock.now, ready_at)
            return data[:size]
        self.clock.now = deadline
        return b""

    def _refuses(self, data: bytes) -> bool:
        if self.clock.now >= self.refuse_out_until_s:
            return False
        return self.refuse_only is None or data == self.refuse_only

    def _take(self, data: bytes) -> None:
        if self._dead:
            return
        if self._stuck:
            self._swallow(len(data))
            return
        self._inbox += data
        if self._inbox == unstick.HELLO:
            reply = self.hello_reply if self.hello_reply is not None else unstick.ACK
            self.hello_reply = None
            self._ready.append((self.clock.now + self.reply_after_s, reply))
        elif self._inbox == unstick.FIN:
            self._ready.append((self.clock.now, FIN_REPLY))
            self._ready.extend((self.clock.now, extra) for extra in self.after_fin)
        elif unstick.HELLO.startswith(self._inbox) or unstick.FIN.startswith(self._inbox):
            return  # the rest of the command is still to come
        self._inbox = b""

    def _swallow(self, count: int) -> None:
        self._swallowed += count
        if self.swallow is not None and self._swallowed >= self.swallow:
            self._ready.append((self.clock.now, PARA_FAIL))
            self._stuck = False
            self._dead = not self.recovers

    @property
    def unread(self) -> int:
        """How many replies the scanner has said that nobody read."""
        return len(self._ready)

    @property
    def stream(self) -> bytes:
        """Every byte the scanner took, in order."""
        return b"".join(self.writes)

    @property
    def filler_bytes(self) -> int:
        return sum(len(data) for data in self.writes if set(data) == {0x20})


def cancel_after_reads(count: int, cancel: threading.Event) -> Callable[[FakeScanner], None]:
    """An ``on_read`` hook that sets ``cancel`` once the scanner was read ``count`` times."""

    def hook(scanner: FakeScanner) -> None:
        if scanner.reads >= count:
            cancel.set()

    return hook


class CancelProbe:
    """Sets a cancel event at a chosen moment and remembers when, on the fake clock."""

    def __init__(self, clock: FakeClock) -> None:
        self.event = threading.Event()
        self.at: float | None = None
        self._clock = clock

    def fire(self) -> None:
        if self.at is None:
            self.at = self._clock.now
        self.event.set()

    def latency(self) -> float:
        """Seconds of fake time between the cancel and now (call it after the check stopped)."""
        assert self.at is not None, "the cancel never fired"
        return self._clock.now - self.at
