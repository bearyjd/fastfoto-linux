"""A photo as the results grid shows it."""

from dataclasses import dataclass
from pathlib import Path

from fastfoto_linux.output import WrittenFiles

ENHANCED_SUFFIX = "_a"  # the enhanced copy is "<name>_a.jpg" beside "<name>.jpg"
BACK_SUFFIX = "_b"  # the back is "<name>_b.jpg"


@dataclass(frozen=True)
class PhotoItem:
    """One written photo: its folder, number and the files that exist.

    ``unprocessed_reason`` is set when the files are the whole pages of a sheet that could not be
    turned into a photo: ``original`` and ``back`` are then those pages (``original`` is missing
    when only the back could be read).
    """

    directory: Path
    index: int
    original: Path | None
    enhanced: Path | None
    back: Path | None
    unprocessed_reason: str | None = None

    @property
    def album(self) -> str:
        """The name of the folder the photo is in."""
        return self.directory.name

    @property
    def title(self) -> str:
        """The photo's file name without the extension: the folder may be the output folder."""
        if self.original is not None:
            return self.original.stem
        if self.enhanced is not None:
            return self.enhanced.stem.removesuffix(ENHANCED_SUFFIX)
        if self.unprocessed and self.back is not None:  # a back alone is all there is to show
            return self.back.stem.removesuffix(BACK_SUFFIX)
        return f"Photo {self.index}"

    @property
    def unprocessed(self) -> bool:
        """Whether this is the whole page of a sheet that could not be processed."""
        return self.unprocessed_reason is not None

    @property
    def front(self) -> Path | None:
        """The picture to show by default: the original, else the enhanced copy.

        A page that was not processed has nothing else to show but its back, when that is alone.
        """
        return self.original or self.enhanced or (self.back if self.unprocessed else None)


def item_from_files(files: WrittenFiles) -> PhotoItem:
    return PhotoItem(
        directory=files.directory,
        index=files.index,
        original=files.original,
        enhanced=files.enhanced,
        back=files.back,
        unprocessed_reason=files.unprocessed_reason,
    )
