"""The desktop app with a fake scanner, run in its own process by test_signals.py.

It starts a scan by itself as soon as the "scanner" is found, and the scan waits for a cancel.
Markers say what happened: ``scanning`` once the scan holds, ``cancelled`` when it saw the cancel,
``teardown`` when the app has left its event loop and saves its settings (which, when
``FASTFOTO_TEST_SLOW_TEARDOWN`` gives a number of seconds, then takes that long, like a slow disk).
"""

import os
import sys
import time
from pathlib import Path
from typing import Any

from fastfoto_linux.gui import worker
from fastfoto_linux.gui.form import ScanForm
from fastfoto_linux.gui.qt import app
from fastfoto_linux.gui.qt import bridge as bridge_module
from fastfoto_linux.scanner import ScanTarget
from fastfoto_linux.session import Stage
from tests.cli.fakes import DEVICE
from tests.gui.helpers import cancelled_scan

MARKERS = Path(os.environ["FASTFOTO_TEST_MARKERS"])
HOLD_SECONDS = 60
SLOW_TEARDOWN = float(os.environ.get("FASTFOTO_TEST_SLOW_TEARDOWN", "0"))


def hold_until_cancelled(request: Any, **hooks: Any) -> Any:
    hooks["on_stage"](Stage.SCANNING)
    (MARKERS / "scanning").write_text("1")
    cancel = hooks["cancel"]
    cancel.wait(HOLD_SECONDS)
    (MARKERS / "cancelled").write_text(str(cancel.is_set()))
    return cancelled_scan(MARKERS / "raw", 2)


class ScanAtOnce(bridge_module.Bridge):
    def __init__(self) -> None:
        super().__init__(remember=False, form=ScanForm(output_folder=str(MARKERS)))
        self._started = False
        self.changed.connect(self._go)

    def remember(self) -> None:
        (MARKERS / "teardown").write_text("1")
        time.sleep(SLOW_TEARDOWN)
        super().remember()

    def _go(self) -> None:
        if self.canScan and not self._started:
            self._started = True
            self.startScan()


worker.default_discover = lambda: ScanTarget(device=DEVICE)
worker.run_session = hold_until_cancelled
bridge_module.Bridge = ScanAtOnce
sys.exit(app.main())
