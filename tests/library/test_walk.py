"""Finding the JPEGs of a library without following links."""

import os
from pathlib import Path

import pytest

from fastfoto_linux.library.walk import walk_library


def touch(root: Path, relative: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")


def test_jpegs_are_found_case_insensitively_sorted_and_relative(tmp_path: Path) -> None:
    for name in ("b.jpg", "A.JPEG", "sub/deep/c.JpG", "sub/d.jpeg", ".hidden.jpg"):
        touch(tmp_path, name)
    result = walk_library(tmp_path)
    assert result.jpegs == (".hidden.jpg", "A.JPEG", "b.jpg", "sub/d.jpeg", "sub/deep/c.JpG")


def test_other_formats_are_counted_not_listed(tmp_path: Path) -> None:
    for name in ("a.jpg", "b.png", "c.tif", "sub/d.txt", "e.jpg.bak", "noext"):
        touch(tmp_path, name)
    result = walk_library(tmp_path)
    assert result.jpegs == ("a.jpg",)
    assert result.other_formats == 5


def test_symlinks_are_never_followed(tmp_path: Path) -> None:
    library, outside = tmp_path / "lib", tmp_path / "outside"
    touch(library, "real.jpg")
    touch(outside, "elsewhere.jpg")
    (library / "link.jpg").symlink_to(library / "real.jpg")
    (library / "linked-folder").symlink_to(outside, target_is_directory=True)
    result = walk_library(library)
    assert result.jpegs == ("real.jpg",)
    assert result.symlinks == 2  # the file link and the folder link


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read every folder")
def test_an_unreadable_folder_is_counted_and_the_rest_is_walked(tmp_path: Path) -> None:
    touch(tmp_path, "ok.jpg")
    touch(tmp_path, "locked/hidden.jpg")
    (tmp_path / "locked").chmod(0o000)
    try:
        result = walk_library(tmp_path)
    finally:
        (tmp_path / "locked").chmod(0o755)
    assert result.jpegs == ("ok.jpg",)
    assert result.unreadable_folders == 1


def test_an_empty_library_has_nothing(tmp_path: Path) -> None:
    result = walk_library(tmp_path)
    assert (result.jpegs, result.other_formats, result.symlinks) == ((), 0, 0)


def test_hidden_folders_and_synology_metadata_are_skipped_and_counted(tmp_path: Path) -> None:
    for name in (
        "a.jpg",
        "album/e.jpg",
        ".hidden/b.jpg",
        "album/@eaDir/c.jpg",
        "album/.thumbs/d.jpg",
    ):
        touch(tmp_path, name)
    result = walk_library(tmp_path)
    assert result.jpegs == ("a.jpg", "album/e.jpg")
    assert result.skipped_folders == 3


def test_a_dot_inside_a_name_or_in_a_hidden_file_does_not_hide_anything(tmp_path: Path) -> None:
    touch(tmp_path, "v1.0/a.jpg")
    touch(tmp_path, "v1.0/.hidden-file.jpg")
    result = walk_library(tmp_path)
    assert result.jpegs == ("v1.0/.hidden-file.jpg", "v1.0/a.jpg")
    assert result.skipped_folders == 0


def test_a_library_folder_that_is_itself_hidden_is_still_walked(tmp_path: Path) -> None:
    touch(tmp_path / ".library", "a.jpg")
    assert walk_library(tmp_path / ".library").jpegs == ("a.jpg",)
