"""Subprocess proof that an explicit power job finishes cleanup after main returns."""

import sys
import threading
from pathlib import Path

from fastfoto_linux.gui.power import PowerResult, PowerTools
from fastfoto_linux.gui.worker import Worker
from tests.gui.power_helpers import snapshot

entered = threading.Event()
release = threading.Event()
marker = Path(sys.argv[1])


class Sink:
    def on_power(self, result: PowerResult) -> None:
        assert result.error is None
        marker.write_text("cleanup finished")


def read(*args: object, **kwargs: object) -> object:
    entered.set()
    assert release.wait(3)
    return snapshot()


worker = Worker(Sink(), power=PowerTools(read=read))
worker.read_power()
assert entered.wait(3)
worker.cancel()
timer = threading.Timer(0.3, release.set)
timer.daemon = True
timer.start()
# Main returns now. Only the worker can keep Python alive long enough to finish cleanup.
