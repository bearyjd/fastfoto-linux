"""Writing the corrected copies: only what the plan says, never into the library."""

import os
import stat
from dataclasses import replace
from pathlib import Path

import pytest

from fastfoto_linux.library.apply import (
    REASON_UNSAFE_DESTINATION,
    STATUS_EXISTS,
    STATUS_FAILED,
    STATUS_STALE,
    STATUS_WRITTEN,
    apply_plan,
)
from fastfoto_linux.library.jpeg_exif import read_orientation
from fastfoto_linux.library.plan import Action
from fastfoto_linux.library.safety import UnsafePathError
from tests.library.apply_helpers import (
    FIRST,
    MTIME_NS,
    SECOND,
    THIRD,
    statuses,
    two_rows,
)
from tests.library.jpeg_helpers import (
    manifest_files,
    manifest_rows,
    rotate_row,
    stored_array,
    tree_snapshot,
    write_file,
)

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
    written = [p for p in dest.rglob("*") if p.is_file() and p not in manifest_files(dest)]
    assert [p.relative_to(dest).as_posix() for p in written] == [FIRST]


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
    manifests = [path.name for path in manifest_files(dest)]
    assert len(manifests) == 1
    assert names == sorted([Path(FIRST).name, Path(SECOND).name, *manifests])


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


def test_a_destination_folder_linked_into_the_library_is_refused_for_that_row(
    lib: Path, dest: Path
) -> None:
    (dest / "2001").symlink_to(lib / "2001", target_is_directory=True)
    before = tree_snapshot(lib)
    rows = [*two_rows(lib), rotate_row(lib, THIRD, 90, 1, 6)]
    result = apply_plan(rows, lib, dest)
    assert {o.path: (o.status, o.reason) for o in result.outcomes} == {
        FIRST: (STATUS_FAILED, REASON_UNSAFE_DESTINATION),
        SECOND: (STATUS_FAILED, REASON_UNSAFE_DESTINATION),
        THIRD: (STATUS_WRITTEN, ""),
    }
    assert tree_snapshot(lib) == before


def test_a_row_path_that_leaves_the_library_fails_alone(lib: Path, dest: Path) -> None:
    bad = replace(rotate_row(lib, FIRST, 90, 1, 6), path="../elsewhere.jpg")
    result = apply_plan([bad, rotate_row(lib, SECOND, 90, 6, 3)], lib, dest)
    assert [(o.status, o.reason) for o in result.outcomes] == [
        (STATUS_FAILED, REASON_UNSAFE_DESTINATION),
        (STATUS_WRITTEN, ""),
    ]


# --- manifest ---------------------------------------------------------------------------


def test_the_manifest_lists_what_was_written(lib: Path, dest: Path) -> None:
    write_file(dest, SECOND, b"already here")
    apply_plan(two_rows(lib), lib, dest)
    assert manifest_rows(dest) == [["path", "old_tag", "new_tag"], [FIRST, "1", "6"]]


def test_no_manifest_is_made_when_nothing_was_written(lib: Path, dest: Path) -> None:
    apply_plan([], lib, dest)
    assert manifest_files(dest) == []
