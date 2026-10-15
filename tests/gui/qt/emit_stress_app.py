"""Threads report to a bridge while it is closed and deleted; run in its own process.

``test_bridge_close.py`` runs this with a timeout: a thread that is still inside ``signal.emit``
when the bridge is deleted takes the whole process down (a segmentation fault), which must fail one
test and not kill pytest. Prints ``done N`` when every round survived.
"""

import faulthandler
import random
import sys
import threading
import time

from PySide6.QtWidgets import QApplication

from fastfoto_linux.gui.qt.app import destroy_now
from fastfoto_linux.gui.qt.bridge import Bridge

THREADS = 4
MAX_RUN_SECONDS = 0.004  # how long the reporters run before the bridge is closed
SEED = 1


def report_until(stop: threading.Event, bridge: Bridge) -> None:
    """What the worker thread and the disk check do: hand events to the bridge, over and over."""
    while not stop.is_set():
        bridge.on_page(1)


def one_round(app: QApplication, rng: random.Random) -> None:
    bridge = Bridge(remember=False)
    stop = threading.Event()
    threads = [threading.Thread(target=report_until, args=(stop, bridge)) for _ in range(THREADS)]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + rng.random() * MAX_RUN_SECONDS
    while time.monotonic() < deadline:
        app.processEvents()  # the GUI thread keeps running, like the real app
    bridge.shutdown()
    destroy_now(bridge)  # straight after: a reporter may still be inside the emit
    stop.set()
    for thread in threads:
        thread.join()
    app.processEvents()


def main(rounds: int) -> None:
    faulthandler.enable()
    app = QApplication(["emit-stress"])
    rng = random.Random(SEED)
    for _ in range(rounds):
        one_round(app, rng)
    print(f"done {rounds}")


if __name__ == "__main__":
    main(int(sys.argv[1]))
