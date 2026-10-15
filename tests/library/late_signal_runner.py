"""``ffscan library check`` whose pooled run is stopped by one signal and then by another.

The first signal arrives inside ``stopping.first_interrupt_only`` (the pool's block). The second
arrives while ``main`` is writing "interrupted": after the pool's handlers are long back, before
``main`` has returned.
"""

import signal
import sys
import time
from collections.abc import Callable
from typing import TextIO

from fastfoto_linux.cli import cmd_library
from fastfoto_linux.cli.app import main
from fastfoto_linux.library import stopping

WAIT_S = 30  # the first signal ends the wait at once; this only keeps a failure from hanging
MESSAGE = "interrupted"


class LateSignalStream:
    """stderr that raises one more signal just before it writes the message."""

    def __init__(self, real: TextIO, number: signal.Signals) -> None:
        self.real = real
        self.number = number
        self.sent = False

    def write(self, text: str) -> int:
        if MESSAGE in text and not self.sent:
            self.sent = True
            signal.raise_signal(self.number)
        return self.real.write(text)

    def flush(self) -> None:
        self.real.flush()


def interrupted_in_the_pool(first: signal.Signals) -> Callable[..., object]:
    """A stand-in for ``decide_files`` that is stopped by ``first`` inside the pool's block."""

    def decide(*_args: object, **_kwargs: object) -> None:
        with stopping.first_interrupt_only():
            signal.raise_signal(first)
            time.sleep(WAIT_S)

    return decide


def run(first: signal.Signals, second: signal.Signals, argv: list[str]) -> int:
    cmd_library.decide_files = interrupted_in_the_pool(first)
    sys.stderr = LateSignalStream(sys.stderr, second)
    return main(argv)


if __name__ == "__main__":
    first_number, second_number, *arguments = sys.argv[1:]
    sys.exit(run(signal.Signals(int(first_number)), signal.Signals(int(second_number)), arguments))
