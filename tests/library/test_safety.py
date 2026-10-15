"""The library is read-only: path checks that refuse to write into it."""

from pathlib import Path

import pytest

from fastfoto_linux.library.plan import PLAN_COLUMNS
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
