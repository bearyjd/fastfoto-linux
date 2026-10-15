"""Worker functions for the pool tests; forkserver workers import them by name."""

import os
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
