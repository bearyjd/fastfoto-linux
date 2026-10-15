"""The library is read-only: path checks that refuse to write into it."""

import os
import stat
from pathlib import Path

import pytest

from fastfoto_linux.library import safety
from fastfoto_linux.library.plan import PLAN_COLUMNS, Action, PlanRow, read_plan, write_plan
from fastfoto_linux.library.safety import (
    UnsafePathError,
    assert_outside,
    check_plan_output,
    check_roots,
    resolve_inside,
)


@pytest.fixture
def src(tmp_path: Path) -> Path:
    path = tmp_path / "lib"
    path.mkdir()
    return path


# --- resolve_inside -------------------------------------------------------------------


def test_a_plain_relative_path_resolves_inside(src: Path) -> None:
    assert resolve_inside(src, "a/b.jpg") == src.resolve() / "a" / "b.jpg"


@pytest.mark.parametrize(
    "bad", ["", "/etc/passwd", "../x.jpg", "a/../../x.jpg", "a/./../..", "..", "a\x00b.jpg"]
)
def test_traversal_absolute_and_odd_paths_are_refused(src: Path, bad: str) -> None:
    with pytest.raises(UnsafePathError):
        resolve_inside(src, bad)


def test_a_symlink_that_leaves_the_folder_is_refused(src: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (src / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(UnsafePathError):
        resolve_inside(src, "escape/x.jpg")


# --- check_roots ----------------------------------------------------------------------


def test_disjoint_folders_are_accepted_even_with_a_shared_name_prefix(
    src: Path, tmp_path: Path
) -> None:
    dest = tmp_path / "lib-fixed"
    assert check_roots(src, dest) == (src.resolve(), dest.resolve())


@pytest.mark.parametrize(
    "dest_of",
    [
        lambda src, tmp: src,
        lambda src, tmp: src / "fixed",
        lambda src, tmp: src / "a" / "b",
        lambda src, tmp: tmp,
        lambda src, tmp: tmp.parent,
    ],
    ids=["same", "dest-inside-src", "deep-dest-inside-src", "src-inside-dest", "src-far-inside"],
)
def test_overlapping_folders_are_refused(src: Path, tmp_path: Path, dest_of) -> None:
    with pytest.raises(UnsafePathError, match="overlap"):
        check_roots(src, dest_of(src, tmp_path))


def test_a_symlink_into_the_library_counts_as_inside(src: Path, tmp_path: Path) -> None:
    sneaky = tmp_path / "sneaky"
    sneaky.symlink_to(src, target_is_directory=True)
    with pytest.raises(UnsafePathError, match="overlap"):
        check_roots(src, sneaky)
    with pytest.raises(UnsafePathError, match="overlap"):
        check_roots(sneaky, src / "out")


# --- check_plan_output ----------------------------------------------------------------


def test_a_plan_outside_the_library_is_accepted(src: Path, tmp_path: Path) -> None:
    plan = tmp_path / "plan.csv"
    assert check_plan_output(plan, src) == plan.resolve()


def test_a_plan_inside_the_library_is_refused(src: Path) -> None:
    with pytest.raises(UnsafePathError, match="inside"):
        check_plan_output(src / "plan.csv", src)


def test_a_missing_plan_folder_is_refused(src: Path, tmp_path: Path) -> None:
    with pytest.raises(UnsafePathError, match="folder"):
        check_plan_output(tmp_path / "nope" / "plan.csv", src)


def test_an_old_plan_may_be_replaced_but_other_files_may_not(src: Path, tmp_path: Path) -> None:
    old = tmp_path / "old.csv"
    old.write_text(",".join(PLAN_COLUMNS) + "\r\n")
    assert check_plan_output(old, src) == old.resolve()
    other = tmp_path / "notes.csv"
    other.write_text("my,precious,data\n")
    with pytest.raises(UnsafePathError, match="not a plan"):
        check_plan_output(other, src)
    with pytest.raises(UnsafePathError, match="not a plan"):
        check_plan_output(tmp_path, src)  # a folder


# --- assert_outside -------------------------------------------------------------------


def test_assert_outside_passes_for_a_sibling_and_fails_inside(src: Path, tmp_path: Path) -> None:
    assert_outside(tmp_path / "dest" / "x.jpg", src)
    with pytest.raises(UnsafePathError):
        assert_outside(src / "x.jpg", src)
    with pytest.raises(UnsafePathError):
        assert_outside(src, src)


# --- the same folder under another identity ---------------------------------------------


@pytest.fixture
def twins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """Two different folders that the filesystem identity check reports as one (a bind mount)."""
    first, second = tmp_path / "lib", tmp_path / "bind-of-lib"
    first.mkdir()
    second.mkdir()
    pair = {first.stat().st_ino, second.stat().st_ino}
    real = safety.same_directory
    monkeypatch.setattr(
        safety, "same_directory", lambda a, b: real(a, b) or {a.st_ino, b.st_ino} == pair
    )
    return first, second


def test_two_spellings_of_one_folder_overlap(twins: tuple[Path, Path]) -> None:
    first, second = twins
    with pytest.raises(UnsafePathError):
        check_roots(first, second)


def test_a_destination_below_an_alias_of_the_library_is_refused(twins: tuple[Path, Path]) -> None:
    first, second = twins
    with pytest.raises(UnsafePathError):
        check_roots(first, second / "fixed")
    with pytest.raises(UnsafePathError):
        check_roots(first, second / "not" / "made" / "yet")


def test_a_library_below_an_alias_of_the_destination_is_refused(twins: tuple[Path, Path]) -> None:
    first, second = twins
    deep = second / "photos"
    deep.mkdir()
    with pytest.raises(UnsafePathError):
        check_roots(deep, first)


def test_unrelated_folders_are_not_mistaken_for_aliases(
    twins: tuple[Path, Path], tmp_path: Path
) -> None:
    first, _ = twins
    third = tmp_path / "third"
    third.mkdir()
    check_roots(first, third)
    check_roots(third, first)


# --- where the plan goes ----------------------------------------------------------------


def a_row() -> PlanRow:
    return PlanRow("a.jpg", Action.KEEP, 0, 1, None, 0.5, "upright", 1, 2, "")


def test_a_dangling_symlink_at_the_plan_path_is_refused_and_not_followed(
    src: Path, tmp_path: Path
) -> None:
    victim = tmp_path / "victim.txt"
    link = tmp_path / "plan.csv"
    link.symlink_to(victim)
    with pytest.raises(UnsafePathError):
        check_plan_output(link, src)
    with pytest.raises(UnsafePathError):
        write_plan(link, (a_row(),))
    assert not victim.exists()
    assert link.is_symlink()


def test_a_symlink_to_an_old_plan_is_refused_too(src: Path, tmp_path: Path) -> None:
    real = tmp_path / "real-plan.csv"
    write_plan(real, (a_row(),))
    link = tmp_path / "plan.csv"
    link.symlink_to(real)
    with pytest.raises(UnsafePathError):
        check_plan_output(link, src)
    before = real.read_bytes()
    with pytest.raises(UnsafePathError):
        write_plan(link, (a_row(), a_row()))
    assert real.read_bytes() == before


@pytest.mark.timeout(5)
def test_a_fifo_or_a_folder_at_the_plan_path_is_refused(src: Path, tmp_path: Path) -> None:
    fifo = tmp_path / "fifo.csv"
    os.mkfifo(fifo)
    folder = tmp_path / "folder.csv"
    folder.mkdir()
    for path in (fifo, folder):
        with pytest.raises(UnsafePathError):
            check_plan_output(path, src)
        with pytest.raises(UnsafePathError):
            write_plan(path, (a_row(),))


def test_an_old_plan_is_replaced_by_renaming_a_private_new_file_over_it(
    src: Path, tmp_path: Path
) -> None:
    plan = tmp_path / "plan.csv"
    write_plan(plan, (a_row(),))
    old_inode = plan.stat().st_ino
    newer = (a_row(), PlanRow("b.jpg", Action.KEEP, 0, 1, None, 0.5, "upright", 1, 2, ""))
    write_plan(plan, newer)
    assert plan.stat().st_ino != old_inode
    assert stat.S_IMODE(plan.stat().st_mode) == 0o600
    assert sorted(p.name for p in tmp_path.iterdir() if p.is_file()) == ["plan.csv"]
    assert read_plan(plan, tmp_path) == newer


def test_a_failure_while_writing_leaves_the_old_plan_and_no_staging_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    plan = tmp_path / "plan.csv"
    write_plan(plan, (a_row(),))
    original = plan.read_bytes()

    def disk_full(_fd: int) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "fsync", disk_full)
    with pytest.raises(OSError, match="No space"):
        write_plan(plan, (a_row(), a_row()))
    assert plan.read_bytes() == original
    assert sorted(p.name for p in tmp_path.iterdir()) == ["plan.csv"]
