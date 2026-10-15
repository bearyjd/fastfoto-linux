"""A photo as the results grid shows it."""

from dataclasses import dataclass
from pathlib import Path

from fastfoto_linux.output import WrittenFiles


@dataclass(frozen=True)
class PhotoItem:
    """One written photo: its folder, number and the files that exist."""

    directory: Path
    index: int
    original: Path | None
    enhanced: Path | None
    back: Path | None

    @property
    def album(self) -> str:
        """The name of the folder the photo is in."""
        return self.directory.name

    @property
    def front(self) -> Path | None:
        """The picture to show by default: the original, else the enhanced copy."""
        return self.original or self.enhanced


def item_from_files(files: WrittenFiles) -> PhotoItem:
    return PhotoItem(
        directory=files.directory,
        index=files.index,
        original=files.original,
        enhanced=files.enhanced,
        back=files.back,
    )
