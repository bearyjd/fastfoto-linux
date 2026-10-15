"""Files that are not plain photos, or too big to analyse, become skip rows - never a crash."""

import os
from pathlib import Path

import pytest
from PIL import Image

from fastfoto_linux.library import decide as decide_module
from fastfoto_linux.library import fdio
from fastfoto_linux.library.decide import decide_file
from fastfoto_linux.library.plan import Action
from tests.library.jpeg_helpers import sideways_jpeg, write_file

SMALL_LIMIT = 1000  # pixels: far below the 256 x 256 fixture
BETWEEN_ONE_AND_TWO_TIMES = 40_000


def reason_of(tmp_path: Path) -> tuple[Action, str]:
    row = decide_file(tmp_path, "a.jpg")
    return row.action, row.reason


@pytest.mark.timeout(5)
def test_a_fifo_standing_in_for_a_photo_is_skipped_and_never_opened_blocking(
    tmp_path: Path,
) -> None:
    os.mkfifo(tmp_path / "a.jpg")
    assert reason_of(tmp_path) == (Action.SKIP, "unreadable")


def test_a_link_standing_in_for_a_photo_is_not_followed(tmp_path: Path) -> None:
    write_file(tmp_path, "real.bin", sideways_jpeg(90, None))
    (tmp_path / "a.jpg").symlink_to("real.bin")
    assert reason_of(tmp_path) == (Action.SKIP, "unreadable")


def test_a_file_over_the_size_cap_is_skipped_before_it_is_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    data = sideways_jpeg(90, None)
    write_file(tmp_path, "a.jpg", data)
    monkeypatch.setattr(fdio, "MAX_FILE_BYTES", len(data) - 1)
    assert reason_of(tmp_path) == (Action.SKIP, "too-large")


def test_a_memory_error_while_deciding_skips_the_file_as_too_large(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def out_of_memory(*_args: object, **_kwargs: object) -> None:
        raise MemoryError

    write_file(tmp_path, "a.jpg", sideways_jpeg(90, None))
    monkeypatch.setattr(decide_module, "decide_orientation", out_of_memory)
    assert reason_of(tmp_path) == (Action.SKIP, "too-large")


@pytest.mark.parametrize("limit", [SMALL_LIMIT, BETWEEN_ONE_AND_TWO_TIMES], ids=["far", "near"])
def test_an_image_over_the_pixel_limit_is_skipped_as_too_large(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, limit: int
) -> None:
    write_file(tmp_path, "a.jpg", sideways_jpeg(90, None))
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", limit)
    assert reason_of(tmp_path) == (Action.SKIP, "too-large")


def test_the_pixel_limit_is_set_explicitly_when_the_module_is_imported() -> None:
    assert decide_module.MAX_IMAGE_PIXELS == 200_000_000
    assert Image.MAX_IMAGE_PIXELS == decide_module.MAX_IMAGE_PIXELS
