"""A fake scanner behind ``UsbTransport`` and a clock it drives, for the pre-scan check tests."""

import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

from fastfoto_linux.scanner import unstick
from fastfoto_linux.scanner.unstick import TransportError

PARA_FAIL = b"PARAx0000000#parFAIL#" + b"-" * 43
FIN_REPLY = b"FIN x0000000#" + b"-" * 51
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
    """

    clock: FakeClock
    swallow: int | None = 0
    reply_after_s: float = 0.0
    recovers: bool = True
    hello_reply: bytes | None = None
    stale: tuple[bytes, ...] = ()
    fail_writes: bool = False
    on_read: "Callable[[FakeScanner], None] | None" = None
    writes: list[bytes] = field(default_factory=list)
    reads: int = 0
    _ready: deque[tuple[float, bytes]] = field(default_factory=deque)
    _swallowed: int = 0
    _stuck: bool = False
    _dead: bool = False

    def __post_init__(self) -> None:
        self._stuck = self.swallow != 0
        self._ready.extend((0.0, data) for data in self.stale)

    def write(self, data: bytes) -> None:
        if self.fail_writes:
            raise TransportError("bulk OUT failed")
        self.writes.append(data)
        if self._dead:
            return
        if self._stuck:
            self._swallow(len(data))
        elif data == unstick.HELLO:
            reply = self.hello_reply if self.hello_reply is not None else unstick.ACK
            self.hello_reply = None
            self._ready.append((self.clock.now + self.reply_after_s, reply))
        elif data == unstick.FIN:
            self._ready.append((self.clock.now, FIN_REPLY))

    def read(self, size: int, timeout_ms: int) -> bytes:
        self.reads += 1
        if self.on_read is not None:
            self.on_read(self)
        deadline = self.clock.now + timeout_ms / 1000
        if self._ready and self._ready[0][0] <= deadline:
            ready_at, data = self._ready.popleft()
            self.clock.now = max(self.clock.now, ready_at)
            return data[:size]
        self.clock.now = deadline
        return b""

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
    def filler_bytes(self) -> int:
        return sum(len(data) for data in self.writes if set(data) == {0x20})


def cancel_after_reads(count: int, cancel: threading.Event) -> Callable[[FakeScanner], None]:
    """An ``on_read`` hook that sets ``cancel`` once the scanner was read ``count`` times."""

    def hook(scanner: FakeScanner) -> None:
        if scanner.reads >= count:
            cancel.set()

    return hook
