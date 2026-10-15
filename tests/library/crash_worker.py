"""Worker functions for the pool tests; forkserver workers import them by name."""

import os
import time
from pathlib import Path

from fastfoto_linux.library.decide import decide_file
from fastfoto_linux.library.plan import PlanRow

POISON = "poison.jpg"
FLAKY = "flaky.jpg"
MARKER = "flaky-died-once"  # in the folder above the library


def die_on_poison(src: str, relative: str) -> PlanRow:
    if relative == POISON:
        os._exit(1)
    return decide_file(Path(src), relative)


def die_once_on_flaky(src: str, relative: str) -> PlanRow:
    marker = Path(src).parent / MARKER
    if relative == FLAKY and not marker.exists():
        marker.write_bytes(b"x")
        os._exit(1)
    return decide_file(Path(src), relative)


BUSY_FOLDER = "busy"  # in the folder above the library: one marker file per file being worked on
BUSY_SECONDS = 40


def busy_forever(src: str, relative: str) -> PlanRow:
    """Say that work has started on ``relative``, then stay busy far longer than any test waits."""
    marker = Path(src).parent / BUSY_FOLDER / relative
    marker.write_bytes(b"x")
    time.sleep(BUSY_SECONDS)
    return decide_file(Path(src), relative)


def raise_on_poison(src: str, relative: str) -> PlanRow:
    if relative == POISON:
        raise RuntimeError("this worker fails with an ordinary exception")
    return decide_file(Path(src), relative)
