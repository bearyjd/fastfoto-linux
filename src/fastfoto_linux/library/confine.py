"""Opening folders one step at a time without following links, outside the library."""

import os
from pathlib import Path


def open_folder(path: Path, *, create: bool = False, last_mode: int | None = None) -> int:
    raise NotImplementedError


def refuse_inside(fd: int, library: os.stat_result) -> None:
    raise NotImplementedError
