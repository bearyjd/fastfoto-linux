from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from fastfoto_linux.pipeline.io import load_frame


def _pixels() -> np.ndarray:
    return np.random.default_rng(0).integers(0, 256, size=(12, 8, 3), dtype=np.uint8)


def _save(path: Path, *, dpi: tuple[float, float] | None, mode: str = "RGB") -> np.ndarray:
    pixels = _pixels()
    image = Image.fromarray(pixels).convert(mode)
    image.save(path, dpi=dpi) if dpi else image.save(path)
    return pixels


@pytest.mark.parametrize("dpi", [75, 150, 300, 600])
def test_dpi_is_read_from_the_file_and_rounded(tmp_path: Path, dpi: int) -> None:
    path = tmp_path / "page.png"
    pixels = _save(path, dpi=(dpi, dpi))
    frame, found_dpi = load_frame(path)
    assert found_dpi == dpi
    assert isinstance(found_dpi, int)
    assert frame.dtype == np.uint8
    assert np.array_equal(frame, pixels)


def test_scanimage_style_fractional_dpi_rounds_to_nearest(tmp_path: Path) -> None:
    path = tmp_path / "page.png"
    _save(path, dpi=(599.9988, 599.9988))
    with Image.open(path) as image:
        assert image.info["dpi"][0] != 600  # pHYs stores pixels per metre, so it is inexact
    assert load_frame(path)[1] == 600


def test_returned_array_is_writable_and_independent_of_the_file(tmp_path: Path) -> None:
    path = tmp_path / "page.png"
    pixels = _save(path, dpi=(300, 300))
    frame, _ = load_frame(path)
    frame[:] = 0
    assert np.array_equal(load_frame(path)[0], pixels)


def test_missing_dpi_without_argument_raises(tmp_path: Path) -> None:
    path = tmp_path / "page.png"
    _save(path, dpi=None)
    with pytest.raises(ValueError, match="no dpi metadata"):
        load_frame(path)


def test_explicit_dpi_fills_in_for_missing_metadata(tmp_path: Path) -> None:
    path = tmp_path / "page.png"
    pixels = _save(path, dpi=None)
    frame, dpi = load_frame(path, dpi=200)
    assert dpi == 200
    assert np.array_equal(frame, pixels)


def test_explicit_dpi_takes_precedence_over_the_file(tmp_path: Path) -> None:
    path = tmp_path / "page.png"
    _save(path, dpi=(600, 600))
    assert load_frame(path, dpi=300)[1] == 300


@pytest.mark.parametrize("dpi", [0, -1])
def test_non_positive_explicit_dpi_is_rejected(tmp_path: Path, dpi: int) -> None:
    path = tmp_path / "page.png"
    _save(path, dpi=None)
    with pytest.raises(ValueError, match="positive"):
        load_frame(path, dpi=dpi)


def test_non_square_pixels_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "page.png"
    _save(path, dpi=(300, 600))
    with pytest.raises(ValueError, match="non-square"):
        load_frame(path)


@pytest.mark.parametrize("mode", ["L", "RGBA"])
def test_only_rgb_images_are_accepted(tmp_path: Path, mode: str) -> None:
    path = tmp_path / "page.png"
    _save(path, dpi=(300, 300), mode=mode)
    with pytest.raises(ValueError, match="RGB"):
        load_frame(path)


def test_missing_file_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_frame(tmp_path / "absent.png")


def test_accepts_a_string_path(tmp_path: Path) -> None:
    path = tmp_path / "page.png"
    _save(path, dpi=(300, 300))
    assert load_frame(str(path))[1] == 300
