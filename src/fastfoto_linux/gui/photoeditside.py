"""Qt-free photo review lifecycle contract (RED scaffold)."""

from pathlib import Path
from typing import TYPE_CHECKING

from fastfoto_linux.gui.photoeditjobs import PhotoEditTools
from fastfoto_linux.gui.photos import PhotoItem

if TYPE_CHECKING:
    from fastfoto_linux.gui.controller import Controller


def eligibility(item: PhotoItem) -> str:
    """Explain why a saved result cannot supply the retained, processed original."""
    raise NotImplementedError("photo eligibility awaits the recorded RED baseline")


class PhotoEditSide:
    def __init__(
        self,
        controller: "Controller",
        *,
        cache_dir: Path,
        tools: PhotoEditTools | None = None,
    ) -> None:
        raise NotImplementedError("photo review lifecycle awaits the recorded RED baseline")
