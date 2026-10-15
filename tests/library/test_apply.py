"""Writing the corrected copies: only what the plan says, never into the library."""

import os
import stat
from dataclasses import replace
from pathlib import Path

import pytest

from fastfoto_linux.library.apply import (
    MANIFEST_NAME,
    STATUS_EXISTS,
    STATUS_FAILED,
    STATUS_STALE,
    STATUS_WRITTEN,
    apply_plan,
)
from fastfoto_linux.library.jpeg_exif import read_orientation
from fastfoto_linux.library.plan import Action
from fastfoto_linux.library.safety import UnsafePathError
from tests.face_images import load_astronaut
from tests.library.jpeg_helpers import (
    exif_bytes,
    make_jpeg,
    rotate_row,
    stored_array,
    tree_snapshot,
    write_file,
)

MTIME_NS = 1_100_000_000_123_456_789
FIRST, SECOND, THIRD = "2001/trip_0001_a.jpg", "2001/trip_0002_a.jpg", "b.jpg"


def jpeg(tag: int | None) -> bytes:
    return make_jpeg(load_astronaut(), exif=None if tag is None else exif_bytes(tag, date=True))


@pytest.fixture
def lib(tmp_path: Path) -> Path:
    root = tmp_path / "lib"
    write_file(root, FIRST, jpeg(None), mtime_ns=MTIME_NS)
    write_file(root, SECOND, jpeg(6), mtime_ns=MTIME_NS + 10)
    write_file(root, THIRD, jpeg(1), mtime_ns=MTIME_NS + 20)
    return root


@pytest.fixture
def dest(tmp_path: Path) -> Path:
    path = tmp_path / "dest"
    path.mkdir()
    return path


def two_rows(lib: Path):
    return (
        rotate_row(lib, FIRST, 90, 1, 6),
        rotate_row(lib, SECOND, 90, 6, 3),
    )


def statuses(result) -> dict[str, str]:
    return {outcome.path: outcome.status for outcome in result.outcomes}


# --- what gets written ----------------------------------------------------------------


def test_rotate_rows_become_copies_with_only_the_tag_changed(lib: Path, dest: Path) -> None:
    result = apply_plan(two_rows(lib), lib, dest)
    assert statuses(result) == {FIRST: STATUS_WRITTEN, SECOND: STATUS_WRITTEN}
    assert read_orientation((dest / FIRST).read_bytes()) == 6
    assert read_orientation((dest / SECOND).read_bytes()) == 3
    for name in (FIRST, SECOND):
        assert stored_array((dest / name).read_bytes()).tobytes() == (
            stored_array((lib / name).read_bytes()).tobytes()
        )
    assert result.count(STATUS_WRITTEN) == 2


def test_other_actions_write_nothing(lib: Path, dest: Path) -> None:
    rotate = rotate_row(lib, FIRST, 90, 1, 6)
    others = [
        replace(rotate_row(lib, name, 90, 1, 6), action=a)
        for name, a in (
            (SECOND, Action.KEEP),
            (THIRD, Action.SKIP),
        )
    ]
    others.append(replace(rotate, path=THIRD, action=Action.REVIEW))
    result = apply_plan([*others, rotate], lib, dest)
    assert [outcome.path for outcome in result.outcomes] == [FIRST]
    assert sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file()) == [
        FIRST,
        MANIFEST_NAME,
    ]


def test_the_destination_mirrors_the_relative_paths(lib: Path, dest: Path) -> None:
    apply_plan(two_rows(lib), lib, dest)
    assert (dest / "2001").is_dir()
    assert {p.relative_to(dest).as_posix() for p in dest.rglob("*.jpg")} == {FIRST, SECOND}


def test_times_and_permissions_are_copied(lib: Path, dest: Path) -> None:
    (lib / FIRST).chmod(0o640)
    os.utime(lib / FIRST, ns=(MTIME_NS, MTIME_NS))
    apply_plan([rotate_row(lib, FIRST, 90, 1, 6)], lib, dest)
    info = (dest / FIRST).stat()
    assert info.st_mtime_ns == MTIME_NS
    assert stat.S_IMODE(info.st_mode) == 0o640


def test_the_library_is_byte_identical_afterwards(lib: Path, dest: Path) -> None:
    before = tree_snapshot(lib)
    mtimes = {p: p.stat().st_mtime_ns for p in lib.rglob("*.jpg")}
    apply_plan(two_rows(lib), lib, dest)
    assert tree_snapshot(lib) == before
    assert {p: p.stat().st_mtime_ns for p in lib.rglob("*.jpg")} == mtimes


def test_no_staging_files_are_left_behind(lib: Path, dest: Path) -> None:
    apply_plan(two_rows(lib), lib, dest)
    names = sorted(p.name for p in dest.rglob("*") if p.is_file())
    assert names == sorted([Path(FIRST).name, Path(SECOND).name, MANIFEST_NAME])


# --- existing files and stale rows ----------------------------------------------------


def test_an_existing_destination_file_is_never_overwritten(lib: Path, dest: Path) -> None:
    write_file(dest, FIRST, b"precious")
    result = apply_plan(two_rows(lib), lib, dest)
    assert statuses(result) == {FIRST: STATUS_EXISTS, SECOND: STATUS_WRITTEN}
    assert (dest / FIRST).read_bytes() == b"precious"


def test_an_existing_symlink_in_the_destination_is_not_followed(
    lib: Path, dest: Path, tmp_path: Path
) -> None:
    target = write_file(tmp_path, "elsewhere.jpg", b"keep me")
    (dest / "2001").mkdir()
    (dest / FIRST).symlink_to(target)
    result = apply_plan(two_rows(lib), lib, dest)
    assert statuses(result)[FIRST] == STATUS_EXISTS
    assert target.read_bytes() == b"keep me"


def stale_by_growing(path: Path) -> None:
    with path.open("ab") as handle:
        handle.write(b"x")


def stale_by_touching(path: Path) -> None:
    os.utime(path, ns=(MTIME_NS + 5, MTIME_NS + 5))


def stale_by_same_size_edit(path: Path) -> None:
    info = path.stat()
    data = bytearray(path.read_bytes())
    data[-3] ^= 0xFF
    path.write_bytes(bytes(data))
    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))


def stale_by_deleting(path: Path) -> None:
    path.unlink()


def stale_by_symlinking(path: Path) -> None:
    data = path.read_bytes()
    elsewhere = path.parent / "real.bin"
    elsewhere.write_bytes(data)
    path.unlink()
    path.symlink_to(elsewhere)


@pytest.mark.parametrize(
    "change",
    [
        stale_by_growing,
        stale_by_touching,
        stale_by_same_size_edit,
        stale_by_deleting,
        stale_by_symlinking,
    ],
)
def test_a_stale_row_is_refused_and_the_others_still_apply(lib: Path, dest: Path, change) -> None:
    rows = two_rows(lib)
    change(lib / FIRST)
    result = apply_plan(rows, lib, dest)
    assert statuses(result) == {FIRST: STATUS_STALE, SECOND: STATUS_WRITTEN}
    assert not (dest / FIRST).exists()
    assert next(o for o in result.outcomes if o.path == FIRST).reason


def test_a_row_whose_old_tag_is_wrong_is_refused(lib: Path, dest: Path) -> None:
    wrong = replace(rotate_row(lib, SECOND, 90, 6, 3), old_tag=3, new_tag=8)
    result = apply_plan([wrong], lib, dest)
    assert statuses(result) == {SECOND: STATUS_STALE}
    assert not (dest / SECOND).exists()


def test_a_rotate_row_without_a_hash_is_refused(lib: Path, dest: Path) -> None:
    unhashed = replace(rotate_row(lib, FIRST, 90, 1, 6), sha256="")
    assert statuses(apply_plan([unhashed], lib, dest)) == {FIRST: STATUS_STALE}


def test_a_file_that_cannot_be_edited_fails_alone(lib: Path, dest: Path) -> None:
    write_file(lib, "junk.jpg", b"not a jpeg at all")
    junk = rotate_row(lib, "junk.jpg", 90, 1, 6)
    result = apply_plan([junk, *two_rows(lib)], lib, dest)
    assert statuses(result) == {
        "junk.jpg": STATUS_FAILED,
        FIRST: STATUS_WRITTEN,
        SECOND: STATUS_WRITTEN,
    }
    assert not (dest / "junk.jpg").exists()


# --- safety ---------------------------------------------------------------------------


def test_a_destination_inside_the_library_is_refused_before_anything_is_written(lib: Path) -> None:
    before = tree_snapshot(lib)
    with pytest.raises(UnsafePathError):
        apply_plan(two_rows(lib), lib, lib / "fixed")
    assert tree_snapshot(lib) == before


def test_a_library_inside_the_destination_is_refused(lib: Path, tmp_path: Path) -> None:
    with pytest.raises(UnsafePathError):
        apply_plan(two_rows(lib), lib, tmp_path)


def test_a_destination_folder_linked_into_the_library_is_caught_at_the_write(
    lib: Path, dest: Path
) -> None:
    (dest / "2001").symlink_to(lib / "2001", target_is_directory=True)
    before = tree_snapshot(lib)
    with pytest.raises(UnsafePathError):
        apply_plan([rotate_row(lib, FIRST, 90, 1, 6)], lib, dest)
    assert tree_snapshot(lib) == before


def test_a_row_path_that_leaves_the_library_is_refused(lib: Path, dest: Path) -> None:
    row = replace(rotate_row(lib, FIRST, 90, 1, 6), path="../elsewhere.jpg")
    with pytest.raises(UnsafePathError):
        apply_plan([row], lib, dest)


# --- manifest -------------------------------------------------------------------------


def manifest_lines(dest: Path) -> list[str]:
    return (dest / MANIFEST_NAME).read_text(encoding="utf-8").splitlines()


def test_the_manifest_lists_what_was_written(lib: Path, dest: Path) -> None:
    write_file(dest, SECOND, b"already here")
    apply_plan(two_rows(lib), lib, dest)
    assert manifest_lines(dest) == ["path,old_tag,new_tag", f"{FIRST},1,6"]


def test_a_second_run_adds_to_the_manifest_without_a_second_header(lib: Path, dest: Path) -> None:
    apply_plan([rotate_row(lib, FIRST, 90, 1, 6)], lib, dest)
    apply_plan([rotate_row(lib, SECOND, 90, 6, 3)], lib, dest)
    assert manifest_lines(dest) == ["path,old_tag,new_tag", f"{FIRST},1,6", f"{SECOND},6,3"]


def test_no_manifest_is_made_when_nothing_was_written(lib: Path, dest: Path) -> None:
    apply_plan([], lib, dest)
    assert not (dest / MANIFEST_NAME).exists()
