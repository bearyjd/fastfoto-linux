import errno
import os
from pathlib import Path

import pytest

from fastfoto_linux.output.errors import OutputCollisionError
from fastfoto_linux.output.files import write_new_files


def listing(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir())


def test_writes_every_file_with_its_content_and_leaves_no_temp_files(tmp_path: Path) -> None:
    write_new_files([(tmp_path / "a.jpg", b"AAA"), (tmp_path / "b.jpg", b"BBB")])

    assert listing(tmp_path) == ["a.jpg", "b.jpg"]
    assert (tmp_path / "a.jpg").read_bytes() == b"AAA"
    assert (tmp_path / "b.jpg").read_bytes() == b"BBB"


def test_new_files_get_the_default_umask_permissions(tmp_path: Path) -> None:
    reference = tmp_path / "reference"
    reference.write_bytes(b"")

    write_new_files([(tmp_path / "a.jpg", b"AAA")])

    assert (tmp_path / "a.jpg").stat().st_mode == reference.stat().st_mode


def test_an_existing_file_is_never_overwritten_and_nothing_else_is_written(
    tmp_path: Path,
) -> None:
    (tmp_path / "a.jpg").write_bytes(b"precious")

    with pytest.raises(OutputCollisionError) as raised:
        write_new_files([(tmp_path / "a.jpg", b"new"), (tmp_path / "b.jpg", b"BBB")])

    assert isinstance(raised.value, FileExistsError)
    assert (tmp_path / "a.jpg").read_bytes() == b"precious"
    assert listing(tmp_path) == ["a.jpg"]


def test_a_collision_on_a_later_file_rolls_back_the_earlier_ones(tmp_path: Path) -> None:
    (tmp_path / "b.jpg").write_bytes(b"precious")

    with pytest.raises(OutputCollisionError, match=r"b\.jpg"):
        write_new_files([(tmp_path / "a.jpg", b"AAA"), (tmp_path / "b.jpg", b"new")])

    assert listing(tmp_path) == ["b.jpg"]
    assert (tmp_path / "b.jpg").read_bytes() == b"precious"


def test_an_io_error_part_way_rolls_back_and_removes_temp_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_link = os.link
    calls = []

    def flaky_link(src: Path, dst: Path) -> None:
        calls.append(dst)
        if len(calls) == 2:
            raise OSError(errno.ENOSPC, "No space left on device")
        real_link(src, dst)

    monkeypatch.setattr(os, "link", flaky_link)

    with pytest.raises(OSError, match="No space"):
        write_new_files([(tmp_path / "a.jpg", b"AAA"), (tmp_path / "b.jpg", b"BBB")])

    assert listing(tmp_path) == []


def test_a_missing_directory_fails_cleanly(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        write_new_files([(tmp_path / "nope" / "a.jpg", b"AAA")])

    assert listing(tmp_path) == []


def test_filesystems_without_hard_links_still_get_new_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_links(src: Path, dst: Path) -> None:
        raise OSError(errno.EPERM, "Operation not permitted")

    monkeypatch.setattr(os, "link", no_links)

    write_new_files([(tmp_path / "a.jpg", b"AAA"), (tmp_path / "b.jpg", b"BBB")])

    assert listing(tmp_path) == ["a.jpg", "b.jpg"]
    assert (tmp_path / "b.jpg").read_bytes() == b"BBB"


def test_without_hard_links_an_existing_file_is_still_never_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_links(src: Path, dst: Path) -> None:
        raise OSError(errno.ENOTSUP, "Operation not supported")

    monkeypatch.setattr(os, "link", no_links)
    (tmp_path / "b.jpg").write_bytes(b"precious")

    with pytest.raises(OutputCollisionError):
        write_new_files([(tmp_path / "a.jpg", b"AAA"), (tmp_path / "b.jpg", b"new")])

    assert listing(tmp_path) == ["b.jpg"]
    assert (tmp_path / "b.jpg").read_bytes() == b"precious"


def test_without_hard_links_an_io_error_rolls_back_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_links(src: Path, dst: Path) -> None:
        raise OSError(errno.EPERM, "Operation not permitted")

    real_replace = os.replace
    replaced = []

    def flaky_replace(src: Path, dst: Path) -> None:
        replaced.append(dst)
        if len(replaced) == 2:
            raise OSError(errno.EIO, "Input/output error")
        real_replace(src, dst)

    monkeypatch.setattr(os, "link", no_links)
    monkeypatch.setattr(os, "replace", flaky_replace)

    with pytest.raises(OSError, match="Input/output"):
        write_new_files([(tmp_path / "a.jpg", b"AAA"), (tmp_path / "b.jpg", b"BBB")])

    assert listing(tmp_path) == []


def test_no_items_is_a_no_op(tmp_path: Path) -> None:
    write_new_files([])

    assert listing(tmp_path) == []
