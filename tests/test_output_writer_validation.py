from dataclasses import FrozenInstanceError
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from fastfoto_linux import output
from fastfoto_linux.output.errors import (
    InvalidAlbumError,
    InvalidImageError,
    InvalidNotesError,
    InvalidPrefixError,
)
from fastfoto_linux.output.metadata import MAX_NOTES_CHARS
from fastfoto_linux.output.writer import DEFAULT_QUALITY, MAX_DPI, write_photo
from tests._output_helpers import DPI, HEIGHT, WIDTH, make_root, rgb


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"album": ""}, InvalidAlbumError),
        ({"album": ".."}, InvalidAlbumError),
        ({"prefix": ".."}, InvalidPrefixError),
        ({"prefix": ""}, InvalidPrefixError),
        ({"prefix": "/"}, InvalidPrefixError),
        ({"prefix": "../.."}, InvalidPrefixError),
        ({"notes": "x" * (MAX_NOTES_CHARS + 1)}, InvalidNotesError),
        ({"dpi": 0}, ValueError),
        ({"dpi": -300}, ValueError),
        ({"dpi": 300.5}, ValueError),
        ({"dpi": MAX_DPI + 1}, ValueError),
        ({"dpi": np.int64(MAX_DPI + 1)}, ValueError),
        ({"dpi": np.float64(300)}, ValueError),
        ({"dpi": True}, ValueError),
        ({"dpi": "300"}, ValueError),
        ({"quality": 0}, ValueError),
        ({"quality": 101}, ValueError),
        ({"quality": True}, ValueError),
        ({"quality": 80.5}, ValueError),
    ],
)
def test_bad_arguments_fail_before_anything_touches_the_disk(
    tmp_path: Path, kwargs: dict[str, object], error: type[Exception]
) -> None:
    root = make_root(tmp_path)
    arguments: dict[str, object] = {"dpi": DPI, "output_root": root}
    arguments.update(kwargs)

    with pytest.raises(error):
        write_photo(rgb(), **arguments)  # type: ignore[arg-type]

    assert list(root.iterdir()) == []


@pytest.mark.parametrize("dpi", [np.int64(300), np.uint16(600), np.int32(1), 1, MAX_DPI])
def test_dpi_accepts_numpy_integers_up_to_the_maximum(tmp_path: Path, dpi: int) -> None:
    result = write_photo(rgb(), dpi=dpi, output_root=tmp_path)

    with Image.open(result.original) as image:
        assert tuple(round(v) for v in image.info["dpi"]) == (int(dpi), int(dpi))


def test_quality_accepts_numpy_integers(tmp_path: Path) -> None:
    result = write_photo(rgb(), dpi=DPI, output_root=tmp_path, quality=np.int64(80))

    assert result.original is not None


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
    root = make_root(tmp_path)

    with pytest.raises(InvalidImageError, match="front"):
        write_photo(bad, dpi=DPI, output_root=root)  # type: ignore[arg-type]

    assert list(root.iterdir()) == []


@pytest.mark.parametrize("slot", ["back", "enhanced"])
@pytest.mark.parametrize("bad", [b for b in BAD_IMAGES if b is not None])
def test_optional_images_must_also_be_non_empty_uint8_rgb_arrays(
    tmp_path: Path, slot: str, bad: object
) -> None:
    root = make_root(tmp_path)

    with pytest.raises(InvalidImageError, match=slot):
        write_photo(rgb(), dpi=DPI, output_root=root, **{slot: bad})  # type: ignore[arg-type]

    assert list(root.iterdir()) == []


def test_written_files_is_frozen(tmp_path: Path) -> None:
    result = write_photo(rgb(), dpi=DPI, output_root=tmp_path)

    with pytest.raises(FrozenInstanceError):
        result.index = 99  # type: ignore[misc]


def test_package_exports_the_public_api() -> None:
    assert output.write_photo is write_photo
    assert output.DEFAULT_QUALITY == DEFAULT_QUALITY
    for name in output.__all__:
        assert hasattr(output, name)
