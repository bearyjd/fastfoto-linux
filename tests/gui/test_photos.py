from pathlib import Path

from fastfoto_linux.gui.photos import PhotoItem, item_from_files
from fastfoto_linux.output import WrittenFiles

DIRECTORY = Path("/srv/demo/FastFoto/Family Trips")


def files(**overrides: Path | None) -> WrittenFiles:
    base: dict[str, Path | None] = {
        "original": DIRECTORY / "Family Trips_0003.jpg",
        "enhanced": DIRECTORY / "Family Trips_0003_a.jpg",
        "back": DIRECTORY / "Family Trips_0003_b.jpg",
    }
    return WrittenFiles(directory=DIRECTORY, index=3, **{**base, **overrides})


def test_an_item_carries_the_album_number_and_files() -> None:
    item = item_from_files(files())
    assert item == PhotoItem(
        directory=DIRECTORY,
        index=3,
        original=DIRECTORY / "Family Trips_0003.jpg",
        enhanced=DIRECTORY / "Family Trips_0003_a.jpg",
        back=DIRECTORY / "Family Trips_0003_b.jpg",
    )


def test_the_front_is_the_original() -> None:
    assert item_from_files(files()).album == "Family Trips"
    assert item_from_files(files()).front == DIRECTORY / "Family Trips_0003.jpg"


def test_the_front_is_the_enhanced_copy_when_only_that_was_kept() -> None:
    item = item_from_files(files(original=None, back=None))
    assert item.front == DIRECTORY / "Family Trips_0003_a.jpg"
    assert item.back is None


def test_an_item_with_no_picture_has_no_front() -> None:
    assert item_from_files(files(original=None, enhanced=None)).front is None
