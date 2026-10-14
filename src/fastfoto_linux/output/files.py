"""Write new files without ever overwriting, all-or-nothing."""

from collections.abc import Sequence
from pathlib import Path


def write_new_files(items: Sequence[tuple[Path, bytes]]) -> None:
    """Write every ``(path, data)`` pair as a new file, or none of them."""
    raise NotImplementedError
