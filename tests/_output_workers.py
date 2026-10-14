"""Worker used by the concurrency tests; importable by spawned processes."""

import time
from pathlib import Path

from fastfoto_linux.output import writer
from fastfoto_linux.output.writer import write_photo
from tests._output_helpers import DPI, rgb

ALBUM = "Mix"
NUMBERING_DELAY_S = 0.02


def is_enhanced_only(photo: int) -> bool:
    """Odd photos write only an ``_a`` file, even ones only the plain original."""
    return photo % 2 == 1


def slow_numbering() -> None:
    """Widen the window between choosing an index and publishing, to expose races."""
    real = writer.next_index

    def slow(directory: Path, prefix: str) -> int:
        index = real(directory, prefix)
        time.sleep(NUMBERING_DELAY_S)
        return index

    writer.next_index = slow


def write_numbered(root: str, photo: int, *, slow: bool = False) -> tuple[int, int]:
    """Write photo ``photo`` (noted as ``photo-N``) and return ``(photo, index)``."""
    if slow:
        slow_numbering()
    enhanced_only = is_enhanced_only(photo)
    result = write_photo(
        rgb(),
        dpi=DPI,
        output_root=Path(root),
        album=ALBUM,
        notes=f"photo-{photo}",
        enhanced=rgb() if enhanced_only else None,
        keep_original=not enhanced_only,
    )
    return photo, result.index
