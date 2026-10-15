"""Starting and stopping the pool's worker processes safely.

Stopping: Ctrl-C, SIGTERM and SIGHUP (``ffscan`` turns the last two into KeyboardInterrupt) end a
run once. While the workers are being stopped no further one may land: ``uv run`` sends a second
Ctrl-C soon after the first, and a stop cut short leaves workers running.

Starting: the helper process of the pool is started with ``python -c ...``, which puts the current
folder first on its import path; the folder the user happens to be in must not supply its modules.
"""

import contextlib
import os
import signal
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ProcessPoolExecutor
from types import FrameType

WORKER_JOIN_TIMEOUT_S = 2.0
STOP_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
SAFE_PATH_VARIABLE = "PYTHONSAFEPATH"  # Python 3.11+: no current folder on the import path


def ignore_interrupt() -> None:
    """Workers leave Ctrl-C to the parent, which cancels the queue and exits. They keep SIGTERM:
    it is how the parent stops them."""
    signal.signal(signal.SIGINT, signal.SIG_IGN)


Handler = Callable[[int, FrameType | None], object] | int | signal.Handlers | None


def _restore(previous: dict[signal.Signals, Handler]) -> None:
    for number, handler in previous.items():
        signal.signal(number, handler if handler is not None else signal.SIG_DFL)


@contextlib.contextmanager
def interrupts_ignored() -> Iterator[None]:
    """No stop signal for the length of the block (outside the main thread: no change)."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    previous = {number: signal.signal(number, signal.SIG_IGN) for number in STOP_SIGNALS}
    try:
        yield
    finally:
        _restore(previous)


@contextlib.contextmanager
def first_interrupt_only() -> Iterator[None]:
    """A stop signal raises KeyboardInterrupt once; from the handler's first instruction on, all
    further ones are ignored, so they cannot cut the cleanup short. The previous handlers come
    back afterwards. A signal that is ignored, or has no Python handler, is left as it is, and
    off the main thread nothing changes."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    previous = {number: signal.getsignal(number) for number in STOP_SIGNALS}
    handled = tuple(number for number, handler in previous.items() if callable(handler))

    def interrupt(signum: int, frame: FrameType | None) -> None:
        for number in handled:
            signal.signal(number, signal.SIG_IGN)
        raise KeyboardInterrupt

    for number in handled:
        signal.signal(number, interrupt)
    try:
        yield
    finally:
        _restore({number: previous[number] for number in handled})


def stop_workers(pool: ProcessPoolExecutor) -> None:
    """Cancel the queue and kill the workers, so nothing is left to wait for at exit.

    ``shutdown(wait=False)`` leaves running workers running, and the interpreter then waits for
    them (for as long as their file takes) when it exits. The workers are listed first because
    ``shutdown`` forgets them.
    """
    processes = list((getattr(pool, "_processes", None) or {}).values())
    with interrupts_ignored():
        pool.shutdown(wait=False, cancel_futures=True)
        for process in processes:
            with contextlib.suppress(OSError, ValueError):
                process.terminate()
        for process in processes:
            process.join(WORKER_JOIN_TIMEOUT_S)
            if process.is_alive():
                process.kill()
                process.join(WORKER_JOIN_TIMEOUT_S)


@contextlib.contextmanager
def safe_import_path() -> Iterator[None]:
    """``PYTHONSAFEPATH=1`` for the length of the block, so that the helper processes started
    inside it (the pool starts them at its first job) do not import from the current folder."""
    previous = os.environ.get(SAFE_PATH_VARIABLE)
    os.environ[SAFE_PATH_VARIABLE] = "1"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(SAFE_PATH_VARIABLE, None)
        else:
            os.environ[SAFE_PATH_VARIABLE] = previous
