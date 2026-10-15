"""Threads report to a bridge while it is closed and deleted; run in its own process.

``test_bridge_close.py`` runs this with a timeout: a thread that is still inside ``signal.emit``
when the bridge is deleted takes the whole process down (a segmentation fault) or deadlocks with the
thread that deletes it, which must fail one test and not kill or stall pytest. Prints ``done N``
when every round survived.

A segmentation fault is rare, so a round also checks the cause directly: once ``shutdown`` has
returned, no thread may still be inside ``signal.emit`` (each reporter marks itself while it is
in one). Without the lock between the closed check and the emit that is true in most rounds.
"""

import faulthandler
import random
import sys
import threading
import time

from PySide6.QtWidgets import QApplication

from fastfoto_linux.gui.qt.app import destroy_now
from fastfoto_linux.gui.qt.bridge import Bridge

THREADS = 32  # enough that one is nearly always inside an emit when the GUI thread gets the GIL
MAX_RUN_SECONDS = 0.004  # how long the reporters run before the bridge is closed
SEED = 1


class MarkedEvent:
    """The bridge's event signal, marking its thread in ``inside`` while that is in ``emit``."""

    def __init__(self, bridge: Bridge, inside: list[bool], index: int) -> None:
        self._bridge = bridge
        self._inside = inside
        self._index = index  # one slot per thread: no two threads write the same one

    def emit(self, *args: object) -> None:
        self._inside[self._index] = True
        try:
            self._bridge._event.emit(*args)
        finally:
            self._inside[self._index] = False


def report_until(stop: threading.Event, bridge: Bridge, inside: list[bool], index: int) -> None:
    """What the worker thread and the disk check do: hand events to the bridge, over and over."""
    event = MarkedEvent(bridge, inside, index)
    while not stop.is_set():
        bridge._emit(event, "on_page", 1)


def one_round(app: QApplication, rng: random.Random) -> None:
    bridge = Bridge(remember=False)
    stop = threading.Event()
    inside = [False] * THREADS
    threads = [
        threading.Thread(target=report_until, args=(stop, bridge, inside, index))
        for index in range(THREADS)
    ]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + rng.random() * MAX_RUN_SECONDS
    while time.monotonic() < deadline:
        app.processEvents()  # the GUI thread keeps running, like the real app
    bridge.shutdown()
    still_inside = sum(inside)  # taken at once: shutdown has returned, so none may be inside
    stop.set()  # the reporters leave; one may still be inside the emit, waiting for the GIL
    destroy_now(bridge)
    for thread in threads:
        thread.join()
    app.processEvents()
    if still_inside:
        raise RuntimeError(f"{still_inside} thread(s) were still inside an emit after shutdown")


def main(rounds: int) -> None:
    faulthandler.enable()
    app = QApplication(["emit-stress"])
    rng = random.Random(SEED)
    for _ in range(rounds):
        one_round(app, rng)
    print(f"done {rounds}")


if __name__ == "__main__":
    main(int(sys.argv[1]))
