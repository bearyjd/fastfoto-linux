from dataclasses import FrozenInstanceError
from pathlib import Path

import numpy as np
import pytest

from fastfoto_linux import output
from fastfoto_linux.output.errors import (
    InvalidAlbumError,
    InvalidImageError,
    InvalidNotesError,
    InvalidPrefixError,
)
from fastfoto_linux.output.metadata import MAX_NOTES_CHARS
from fastfoto_linux.output.writer import DEFAULT_QUALITY, write_photo
from tests._output_helpers import DPI, HEIGHT, WIDTH, rgb


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"album": ""}, InvalidAlbumError),
        ({"album": ".."}, InvalidAlbumError),
        ({"prefix": "!!!"}, InvalidPrefixError),
        ({"notes": "x" * (MAX_NOTES_CHARS + 1)}, InvalidNotesError),
        ({"dpi": 0}, ValueError),
        ({"dpi": -300}, ValueError),
        ({"dpi": 300.5}, ValueError),
        ({"quality": 0}, ValueError),
        ({"quality": 101}, ValueError),
    ],
)
def test_bad_arguments_fail_before_anything_touches_the_disk(
    tmp_path: Path, kwargs: dict[str, object], error: type[Exception]
) -> None:
    arguments: dict[str, object] = {"dpi": DPI, "output_root": tmp_path / "out"}
    arguments.update(kwargs)

    with pytest.raises(error):
        write_photo(rgb(), **arguments)  # type: ignore[arg-type]

    assert not (tmp_path / "out").exists()


BAD_IMAGES = [
    np.zeros((HEIGHT, WIDTH), dtype=np.uint8),
    np.zeros((HEIGHT, WIDTH, 4), dtype=np.uint8),
    np.zeros((HEIGHT, WIDTH, 3), dtype=np.float32),
    np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint16),
    np.zeros((0, WIDTH, 3), dtype=np.uint8),
    np.zeros((HEIGHT, 0, 3), dtype=np.uint8),
    [[[0, 0, 0]]],
    None,
]


@pytest.mark.parametrize("bad", BAD_IMAGES)
def test_the_front_must_be_a_non_empty_uint8_rgb_array(tmp_path: Path, bad: object) -> None:
    with pytest.raises(InvalidImageError, match="front"):
        write_photo(bad, dpi=DPI, output_root=tmp_path / "out")  # type: ignore[arg-type]

    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("slot", ["back", "enhanced"])
@pytest.mark.parametrize("bad", [b for b in BAD_IMAGES if b is not None])
def test_optional_images_must_also_be_non_empty_uint8_rgb_arrays(
    tmp_path: Path, slot: str, bad: object
) -> None:
    with pytest.raises(InvalidImageError, match=slot):
        write_photo(rgb(), dpi=DPI, output_root=tmp_path / "out", **{slot: bad})  # type: ignore[arg-type]

    assert not (tmp_path / "out").exists()


def test_written_files_is_frozen(tmp_path: Path) -> None:
    result = write_photo(rgb(), dpi=DPI, output_root=tmp_path)

    with pytest.raises(FrozenInstanceError):
        result.index = 99  # type: ignore[misc]


def test_package_exports_the_public_api() -> None:
    assert output.write_photo is write_photo
    assert output.DEFAULT_QUALITY == DEFAULT_QUALITY
    for name in output.__all__:
        assert hasattr(output, name)
