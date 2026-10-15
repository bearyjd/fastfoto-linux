"""A second stop signal that lands at every step of the stop handler of ``first_interrupt_only``.

For each ``k``, the ``k``-th traced event (a call or a line) of the handler raises a second SIGINT,
delivered at once, inside whatever the handler was doing at that moment: the way a second Ctrl-C
arrives when it arrives at the wrong time. However the handler is built, the block must still end
with one KeyboardInterrupt and a stop that is marked as under way. (A handler that took a lock which
the code it interrupted held would wait for itself, and the process would never exit.)

Prints ``swept N`` (N = the number of steps a signal was raised at) when every one of them ended.
"""

import signal
import sys
import time
from types import FrameType

from fastfoto_linux.library import stopping

MAX_STEPS = 10_000  # more than any handler has; only keeps a runaway sweep finite
WAIT_S = 30  # the first signal ends the wait at once; this only keeps a failure from hanging


class SecondSignalAt:
    """A trace function that raises SIGINT at the ``step``-th event of the handler's run."""

    def __init__(self, step: int) -> None:
        self.step = step
        self.seen = 0
        self.started = False  # the handler (code of ``stopping``) has been called
        self.over = False  # ... and has raised its KeyboardInterrupt
        self.fired = False

    def __call__(self, frame: FrameType, event: str, arg: object) -> "SecondSignalAt":
        if not self.started:
            self.started = event == "call" and frame.f_code.co_filename == stopping.__file__
        if self.started and not self.over:
            if event == "exception" and isinstance(arg, tuple) and arg[0] is KeyboardInterrupt:
                self.over = True
            elif self.seen == self.step:
                self.fired = True
                signal.raise_signal(signal.SIGINT)
            self.seen += 1
        return self


def stopped_with_second_signal_at(step: int) -> bool:
    """Stop a block with one SIGINT and a second at ``step``; whether the second was raised."""
    stopping.forget_stop()
    trace = SecondSignalAt(step)
    try:
        with stopping.first_interrupt_only():
            sys.settrace(trace)
            signal.raise_signal(signal.SIGINT)
            time.sleep(WAIT_S)
    except KeyboardInterrupt:
        pass
    else:
        raise SystemExit(f"step {step}: no KeyboardInterrupt")
    finally:
        sys.settrace(None)
    if not stopping.stop_under_way():
        raise SystemExit(f"step {step}: the stop is not marked as under way")
    if signal.getsignal(signal.SIGINT) is not signal.default_int_handler:
        raise SystemExit(f"step {step}: the previous SIGINT handler did not come back")
    return trace.fired


def main() -> int:
    for number in stopping.STOP_SIGNALS:
        signal.signal(number, signal.default_int_handler)  # the same whatever started this process
    for step in range(MAX_STEPS):
        if not stopped_with_second_signal_at(step):
            print(f"swept {step}")  # the steps before this one each had a signal raised at them
            return 0
    raise SystemExit("the handler never ended")


if __name__ == "__main__":
    sys.exit(main())
