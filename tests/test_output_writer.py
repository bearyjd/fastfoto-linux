import errno
import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, JpegImagePlugin

from fastfoto_linux.output import writer
from fastfoto_linux.output.errors import (
    InvalidAlbumError,
    OutputCollisionError,
    OutputRootMissingError,
)
from fastfoto_linux.output.files import LOCK_NAME
from fastfoto_linux.output.writer import DEFAULT_QUALITY, MAX_INDEX_ATTEMPTS, write_photo
from tests._output_helpers import DPI, HEIGHT, WIDTH, make_root, names, rgb


def test_defaults_write_one_original_named_after_the_album(tmp_path: Path) -> None:
    result = write_photo(rgb(), dpi=DPI, output_root=tmp_path, album="Grandma 1970s")

    folder = tmp_path / "Grandma 1970s"
    assert names(folder) == ["Grandma 1970s_0001.jpg"]
    assert result.directory == folder.resolve()
    assert result.index == 1
    assert result.original == folder.resolve() / "Grandma 1970s_0001.jpg"
    assert result.enhanced is None
    assert result.back is None
    assert result.paths == (result.original,)


def test_without_an_album_files_go_straight_into_the_root(tmp_path: Path) -> None:
    write_photo(rgb(), dpi=DPI, output_root=tmp_path)

    assert names(tmp_path) == ["FastFoto_0001.jpg"]


def test_album_folders_are_created_on_demand_inside_an_existing_root(tmp_path: Path) -> None:
    root = make_root(tmp_path)

    write_photo(rgb(), dpi=DPI, output_root=root, album="Trip")

    assert names(root / "Trip") == ["Trip_0001.jpg"]


def test_a_missing_output_root_is_an_error_and_nothing_is_created(tmp_path: Path) -> None:
    root = tmp_path / "unmounted" / "photos"

    with pytest.raises(OutputRootMissingError, match="photos"):
        write_photo(rgb(), dpi=DPI, output_root=root, album="Trip")

    assert list(tmp_path.rglob("*")) == []


def test_an_output_root_that_is_a_file_is_an_error(tmp_path: Path) -> None:
    (tmp_path / "photos").write_bytes(b"not a folder")

    with pytest.raises(OutputRootMissingError):
        write_photo(rgb(), dpi=DPI, output_root=tmp_path / "photos")


def test_the_lock_file_is_the_only_extra_thing_left_in_the_folder(tmp_path: Path) -> None:
    write_photo(rgb(), dpi=DPI, output_root=tmp_path, album="Trip")

    assert sorted(p.name for p in (tmp_path / "Trip").iterdir()) == [LOCK_NAME, "Trip_0001.jpg"]


def test_an_explicit_prefix_overrides_the_album_name(tmp_path: Path) -> None:
    write_photo(rgb(), dpi=DPI, output_root=tmp_path, album="Trip", prefix="Roll 7!")

    assert names(tmp_path / "Trip") == ["Roll 7!_0001.jpg"]


def test_the_enhanced_copy_is_written_only_when_supplied(tmp_path: Path) -> None:
    plain = write_photo(rgb(), dpi=DPI, output_root=make_root(tmp_path, "p"))
    both = write_photo(
        rgb(), dpi=DPI, output_root=make_root(tmp_path, "b"), enhanced=rgb((10, 20, 30))
    )

    assert plain.enhanced is None
    assert names(tmp_path / "p") == ["FastFoto_0001.jpg"]
    assert both.enhanced is not None
    assert names(tmp_path / "b") == ["FastFoto_0001.jpg", "FastFoto_0001_a.jpg"]


def test_the_back_is_written_only_when_supplied(tmp_path: Path) -> None:
    plain = write_photo(rgb(), dpi=DPI, output_root=make_root(tmp_path, "p"))
    both = write_photo(rgb(), dpi=DPI, output_root=make_root(tmp_path, "b"), back=rgb((10, 20, 30)))

    assert plain.back is None
    assert names(tmp_path / "p") == ["FastFoto_0001.jpg"]
    assert both.back is not None
    assert names(tmp_path / "b") == ["FastFoto_0001.jpg", "FastFoto_0001_b.jpg"]


def test_all_three_files_share_one_index(tmp_path: Path) -> None:
    result = write_photo(
        rgb(), dpi=DPI, output_root=tmp_path, back=rgb(), enhanced=rgb(), album="Trip"
    )

    assert names(tmp_path / "Trip") == ["Trip_0001.jpg", "Trip_0001_a.jpg", "Trip_0001_b.jpg"]
    assert set(result.paths) == {result.original, result.enhanced, result.back}


def test_without_keeping_the_original_only_enhanced_and_back_are_written(tmp_path: Path) -> None:
    result = write_photo(
        rgb(),
        dpi=DPI,
        output_root=tmp_path,
        back=rgb(),
        enhanced=rgb(),
        album="Trip",
        keep_original=False,
    )

    assert names(tmp_path / "Trip") == ["Trip_0001_a.jpg", "Trip_0001_b.jpg"]
    assert result.original is None
    assert result.enhanced is not None
    assert result.back is not None


def test_without_keeping_the_original_but_with_no_enhanced_copy_the_photo_is_still_kept(
    tmp_path: Path,
) -> None:
    result = write_photo(rgb(), dpi=DPI, output_root=tmp_path, album="Trip", keep_original=False)

    assert names(tmp_path / "Trip") == ["Trip_0001.jpg"]
    assert result.original is not None


def test_numbering_continues_in_a_folder_that_holds_only_enhanced_and_back_files(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "1983_June_lake-trip"
    folder.mkdir()
    for name in ("1983_June_lake-trip_0007_a.jpg", "1983_June_lake-trip_0007_b.jpg"):
        (folder / name).write_bytes(b"old")

    result = write_photo(
        rgb(), dpi=DPI, output_root=tmp_path, album="1983_June_lake-trip", enhanced=rgb()
    )

    assert result.index == 8
    assert "1983_June_lake-trip_0008_a.jpg" in names(folder)
    assert (folder / "1983_June_lake-trip_0007_a.jpg").read_bytes() == b"old"


def test_an_album_with_punctuation_keeps_it_in_the_file_names(tmp_path: Path) -> None:
    album = "Mom & Dad (1970s)"

    result = write_photo(rgb(), dpi=DPI, output_root=tmp_path, album=album)

    assert names(tmp_path / album) == ["Mom & Dad (1970s)_0001.jpg"]
    assert result.original == (tmp_path / album).resolve() / "Mom & Dad (1970s)_0001.jpg"


def test_numbering_continues_in_a_folder_whose_name_has_punctuation(tmp_path: Path) -> None:
    album = "Mom & Dad (1970s)"
    folder = tmp_path / album
    folder.mkdir()
    (folder / f"{album}_0012_a.jpg").write_bytes(b"old")
    (folder / f"{album}_0012_b.jpg").write_bytes(b"old")

    result = write_photo(rgb(), dpi=DPI, output_root=tmp_path, album=album, enhanced=rgb())

    assert result.index == 13
    assert result.enhanced == folder.resolve() / "Mom & Dad (1970s)_0013_a.jpg"
    assert (folder / f"{album}_0012_a.jpg").read_bytes() == b"old"


def test_an_explicit_prefix_numbers_by_that_prefix_only(tmp_path: Path) -> None:
    album = "Mom & Dad (1970s)"
    folder = tmp_path / album
    folder.mkdir()
    (folder / f"{album}_0012_a.jpg").write_bytes(b"old")

    result = write_photo(rgb(), dpi=DPI, output_root=tmp_path, album=album, prefix="Roll")

    assert result.index == 1


def test_successive_photos_get_successive_numbers_and_never_touch_earlier_ones(
    tmp_path: Path,
) -> None:
    first = write_photo(rgb((1, 2, 3)), dpi=DPI, output_root=tmp_path, album="Trip")
    before = first.original.read_bytes()
    second = write_photo(rgb((4, 5, 6)), dpi=DPI, output_root=tmp_path, album="Trip")

    assert (first.index, second.index) == (1, 2)
    assert first.original.read_bytes() == before


def stale_next_index(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make numbering miss files, as if another writer published them a moment later."""
    monkeypatch.setattr(writer, "next_index", lambda directory, prefix: 1)


def test_an_index_taken_by_another_writer_is_skipped_without_overwriting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "Trip"
    folder.mkdir()
    (folder / "Trip_0001_b.jpg").write_bytes(b"theirs")
    stale_next_index(monkeypatch)

    result = write_photo(
        rgb(), dpi=DPI, output_root=tmp_path, album="Trip", back=rgb(), enhanced=rgb()
    )

    assert result.index == 2
    assert names(folder) == [
        "Trip_0001_b.jpg",
        "Trip_0002.jpg",
        "Trip_0002_a.jpg",
        "Trip_0002_b.jpg",
    ]
    assert (folder / "Trip_0001_b.jpg").read_bytes() == b"theirs"


def test_giving_up_after_repeated_collisions_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "Trip"
    folder.mkdir()
    for index in range(1, MAX_INDEX_ATTEMPTS + 1):
        (folder / f"Trip_{index:04d}_b.jpg").write_bytes(b"theirs")
    stale_next_index(monkeypatch)

    with pytest.raises(OutputCollisionError):
        write_photo(rgb(), dpi=DPI, output_root=tmp_path, album="Trip", back=rgb(), enhanced=rgb())

    assert names(folder) == [f"Trip_{i:04d}_b.jpg" for i in range(1, MAX_INDEX_ATTEMPTS + 1)]


def test_an_encoder_failure_creates_neither_the_album_folder_nor_any_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    saves = []

    def failing_save(image: Image.Image, fp: object, *args: object, **kwargs: object) -> None:
        saves.append(fp)
        if len(saves) == 2:
            raise OSError("encoder exploded")
        fp.write(b"partial jpeg")  # type: ignore[attr-defined]

    monkeypatch.setattr(Image.Image, "save", failing_save)
    root = make_root(tmp_path)

    with pytest.raises(OSError, match="encoder exploded"):
        write_photo(rgb(), dpi=DPI, output_root=root, album="Trip", back=rgb())

    assert list(root.iterdir()) == []


def test_a_disk_error_while_writing_rolls_back_the_whole_photo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_link = os.link
    calls = []

    def flaky_link(src: Path, dst: Path, **kwargs: bool) -> None:
        calls.append(dst)
        if len(calls) == 2:
            raise OSError(errno.ENOSPC, "No space left on device")
        real_link(src, dst, **kwargs)

    monkeypatch.setattr(os, "link", flaky_link)

    with pytest.raises(OSError, match="No space"):
        write_photo(rgb(), dpi=DPI, output_root=tmp_path, album="Trip", back=rgb())

    assert names(tmp_path / "Trip") == []


def test_output_is_an_rgb_jpeg_of_the_input_size_with_preserved_dpi(tmp_path: Path) -> None:
    result = write_photo(rgb(), dpi=DPI, output_root=tmp_path, back=rgb(), enhanced=rgb())

    for path in result.paths:
        with Image.open(path) as image:
            assert image.format == "JPEG"
            assert image.mode == "RGB"
            assert image.size == (WIDTH, HEIGHT)
            assert tuple(round(v) for v in image.info["dpi"]) == (DPI, DPI)
            assert JpegImagePlugin.get_sampling(image) == 0


def test_the_default_quality_is_95_and_can_be_overridden(tmp_path: Path) -> None:
    rng = np.random.default_rng(0)
    noisy = rng.integers(0, 256, size=(HEIGHT, WIDTH, 3), dtype=np.uint8)

    high = write_photo(noisy, dpi=DPI, output_root=make_root(tmp_path, "hi"))
    low = write_photo(noisy, dpi=DPI, output_root=make_root(tmp_path, "lo"), quality=20)

    assert DEFAULT_QUALITY == 95
    assert high.original.stat().st_size > low.original.stat().st_size


def test_channel_order_is_rgb_not_bgr(tmp_path: Path) -> None:
    result = write_photo(rgb((255, 0, 0)), dpi=DPI, output_root=tmp_path)

    with Image.open(result.original) as image:
        red, green, blue = image.getpixel((WIDTH // 2, HEIGHT // 2))
    assert red > 240
    assert green < 15
    assert blue < 15


def test_inputs_are_not_mutated_and_read_only_arrays_are_accepted(tmp_path: Path) -> None:
    front, back, enhanced = rgb((1, 2, 3)), rgb((4, 5, 6)), rgb((7, 8, 9))
    snapshots = [a.copy() for a in (front, back, enhanced)]

    write_photo(front, dpi=DPI, output_root=tmp_path, back=back, enhanced=enhanced)

    for array, snapshot in zip((front, back, enhanced), snapshots, strict=True):
        assert np.array_equal(array, snapshot)
        assert not array.flags.writeable


def test_non_contiguous_arrays_are_accepted(tmp_path: Path) -> None:
    sliced = np.zeros((HEIGHT * 2, WIDTH * 2, 3), dtype=np.uint8)[::2, ::2]

    write_photo(sliced, dpi=DPI, output_root=tmp_path)

    assert names(tmp_path) == ["FastFoto_0001.jpg"]


@pytest.mark.parametrize("album", ["../../escape", "/tmp/escape", "..\\..\\escape"])
def test_path_traversal_in_the_album_stays_inside_the_output_root(
    tmp_path: Path, album: str
) -> None:
    root = make_root(tmp_path)

    result = write_photo(rgb(), dpi=DPI, output_root=root, album=album)

    assert result.directory.parent == root.resolve()
    assert names(tmp_path) == ["out"]


@pytest.mark.parametrize("prefix", ["../../escape", "/tmp/escape", "..\\..\\escape"])
def test_path_traversal_in_the_prefix_stays_inside_the_album_folder(
    tmp_path: Path, prefix: str
) -> None:
    root = make_root(tmp_path)

    result = write_photo(rgb(), dpi=DPI, output_root=root, album="Trip", prefix=prefix)

    assert result.directory == (root / "Trip").resolve()
    assert result.original is not None
    assert result.original.parent == result.directory
    assert names(tmp_path) == ["out"]
    assert names(root) == ["Trip"]


def test_an_album_symlink_pointing_outside_the_root_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "out"
    root.mkdir()
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (root / "Sneaky").symlink_to(outside, target_is_directory=True)

    with pytest.raises(InvalidAlbumError):
        write_photo(rgb(), dpi=DPI, output_root=root, album="Sneaky")

    assert names(outside) == []
