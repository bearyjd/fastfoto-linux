"""Folders are opened once, from the root down, and the opened folder is what gets written to.

A path that was fine when it was checked can be swapped for a link (or another folder) before the
write hours later; the descriptors opened at the start are what the write must use.
"""

import errno
import os
import stat
from pathlib import Path

import pytest

from fastfoto_linux.cli import cmd_library
from fastfoto_linux.cli.app import main
from fastfoto_linux.library import confine, fdio
from fastfoto_linux.library.apply import apply_plan
from fastfoto_linux.library.plan import PLAN_COLUMNS, Action, PlanRow, write_plan
from fastfoto_linux.library.safety import UnsafePathError
from tests.library.apply_helpers import jpeg
from tests.library.jpeg_helpers import rotate_row, tree_snapshot, write_file

EXIT_USAGE = 2
PRECIOUS = b"PRECIOUS data made while the scan was running\n"


def fd_count() -> int:
    return len(os.listdir("/proc/self/fd"))


def scan_hook(monkeypatch: pytest.MonkeyPatch, hook) -> None:
    """Run ``hook`` after ``check`` has validated its paths and before it writes the plan."""
    real = cmd_library.decide_files

    def scan(src, relatives, jobs):
        hook()
        return real(src, relatives, 1)

    monkeypatch.setattr(cmd_library, "decide_files", scan)


@pytest.fixture
def small_lib(tmp_path: Path) -> Path:
    library = tmp_path / "lib"
    write_file(library, "sub/a.jpg", jpeg(None))
    return library


# --- the plan file ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["file", "dangling-link"])
def test_something_that_appears_at_the_plan_path_during_the_scan_is_refused_and_kept(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, small_lib: Path, kind: str
) -> None:
    out = tmp_path / "out"
    out.mkdir()
    plan = out / "plan.csv"
    target = tmp_path / "never-created"

    def plant() -> None:
        if kind == "file":
            plan.write_bytes(PRECIOUS)
        else:
            plan.symlink_to(target)

    scan_hook(monkeypatch, plant)
    assert main(["library", "check", str(small_lib), "--plan", str(plan)]) == EXIT_USAGE
    assert not target.exists()
    assert plan.is_symlink() if kind != "file" else plan.read_bytes() == PRECIOUS
    assert sorted(path.name for path in out.iterdir()) == ["plan.csv"]  # no staging file left


def test_an_older_plan_that_is_still_a_plan_is_replaced(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, small_lib: Path
) -> None:
    plan = tmp_path / "plan.csv"
    write_plan(plan, ())
    scan_hook(monkeypatch, lambda: None)
    assert main(["library", "check", str(small_lib), "--plan", str(plan)]) == 0
    assert "sub/a.jpg" in plan.read_text()


def test_a_plan_folder_swapped_for_a_link_into_the_library_is_not_followed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, small_lib: Path
) -> None:
    out, moved = tmp_path / "out", tmp_path / "out.moved"
    out.mkdir()

    def swap() -> None:
        out.rename(moved)
        out.symlink_to(small_lib / "sub")

    scan_hook(monkeypatch, swap)
    before = tree_snapshot(small_lib)
    assert main(["library", "check", str(small_lib), "--plan", str(out / "plan.csv")]) == 0
    assert tree_snapshot(small_lib) == before
    assert "sub/a.jpg" in (moved / "plan.csv").read_text()  # written where the folder was opened


def test_a_plan_without_hard_links_on_the_filesystem_is_still_written(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, small_lib: Path
) -> None:
    def no_links(*_args, **_kwargs) -> None:
        raise PermissionError(1, "hard links are not supported")

    monkeypatch.setattr(os, "link", no_links)
    plan = tmp_path / "plan.csv"
    assert main(["library", "check", str(small_lib), "--plan", str(plan), "--jobs", "1"]) == 0
    assert plan.read_text().splitlines()[0] == ",".join(PLAN_COLUMNS)


# --- the destination --------------------------------------------------------------------------


def test_a_destination_ancestor_swapped_for_a_link_into_the_library_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, small_lib: Path
) -> None:
    parent = tmp_path / "parent"
    (parent / "dest").mkdir(parents=True)
    (small_lib / "sub" / "dest").mkdir()
    row = rotate_row(small_lib, "sub/a.jpg", 90, 1, 6)
    real_open_root = fdio.open_root

    def swapped(dest: Path, library: os.stat_result) -> int:
        parent.rename(tmp_path / "parent.moved")
        parent.symlink_to(small_lib / "sub")
        try:
            return real_open_root(dest, library)
        finally:
            parent.unlink()
            (tmp_path / "parent.moved").rename(parent)

    monkeypatch.setattr(fdio, "open_root", swapped)
    before = tree_snapshot(small_lib)
    with pytest.raises(UnsafePathError):
        apply_plan([row], small_lib, parent / "dest")
    assert tree_snapshot(small_lib) == before


def test_a_destination_below_the_library_by_identity_is_refused_and_closed(
    tmp_path: Path,
) -> None:
    """Two spellings of one folder (bind mounts, case folding) differ only by device and inode."""
    inner = tmp_path / "x" / "y"
    inner.mkdir(parents=True)
    before = fd_count()
    with pytest.raises(UnsafePathError):
        fdio.open_root(inner, os.stat(tmp_path / "x"))
    assert fd_count() == before


def test_a_destination_that_is_unrelated_to_the_library_is_opened(tmp_path: Path) -> None:
    (tmp_path / "other").mkdir()
    (tmp_path / "dest").mkdir()
    fd = fdio.open_root(tmp_path / "dest", os.stat(tmp_path / "other"))
    os.close(fd)


def test_fix_mkdir_creates_every_missing_folder_of_the_destination(
    tmp_path: Path, small_lib: Path
) -> None:
    plan, dest = tmp_path / "plan.csv", tmp_path / "a" / "b" / "dest"
    write_plan(plan, (rotate_row(small_lib, "sub/a.jpg", 90, 1, 6),))
    argv = ["library", "fix", str(plan), "--source", str(small_lib), "--out", str(dest)]
    assert main([*argv, "--mkdir"]) == 0
    assert (dest / "sub" / "a.jpg").is_file()


# --- confine -------------------------------------------------------------------------------------


def test_open_folder_opens_an_existing_folder(tmp_path: Path) -> None:
    (tmp_path / "a" / "b").mkdir(parents=True)
    fd = confine.open_folder(tmp_path.resolve() / "a" / "b")
    try:
        assert os.path.samestat(os.fstat(fd), os.stat(tmp_path / "a" / "b"))
    finally:
        os.close(fd)


def test_open_folder_makes_missing_folders_only_when_asked(tmp_path: Path) -> None:
    target = tmp_path.resolve() / "a" / "b" / "c"
    with pytest.raises(FileNotFoundError):
        confine.open_folder(target)
    assert not (tmp_path / "a").exists()
    os.close(confine.open_folder(target, create=True))
    assert target.is_dir()


def test_open_folder_gives_the_last_new_folder_the_requested_mode(tmp_path: Path) -> None:
    previous = os.umask(0o077)
    try:
        fd = confine.open_folder(tmp_path.resolve() / "new", create=True, last_mode=0o750)
    finally:
        os.umask(previous)
    os.close(fd)
    assert stat.S_IMODE((tmp_path / "new").stat().st_mode) == 0o750


@pytest.mark.parametrize("where", ["middle", "last", "file"])
def test_open_folder_refuses_links_and_files_anywhere_on_the_path(
    tmp_path: Path, where: str
) -> None:
    real = tmp_path / "real"
    (real / "b").mkdir(parents=True)
    (real / "plain").write_bytes(b"x")
    (tmp_path / "link").symlink_to(real)
    paths = {
        "middle": tmp_path.resolve() / "link" / "b",
        "last": tmp_path.resolve() / "link",
        "file": real.resolve() / "plain",
    }
    with pytest.raises(UnsafePathError):
        confine.open_folder(paths[where])


def test_refuse_inside_refuses_the_library_its_subfolders_and_nothing_else(tmp_path: Path) -> None:
    (tmp_path / "lib" / "sub" / "deep").mkdir(parents=True)
    (tmp_path / "elsewhere").mkdir()
    library = os.stat(tmp_path / "lib")
    for inside in (tmp_path / "lib", tmp_path / "lib" / "sub" / "deep"):
        fd = os.open(inside, os.O_RDONLY | os.O_DIRECTORY)
        try:
            with pytest.raises(UnsafePathError):
                confine.refuse_inside(fd, library)
        finally:
            os.close(fd)
    fd = os.open(tmp_path / "elsewhere", os.O_RDONLY | os.O_DIRECTORY)
    try:
        confine.refuse_inside(fd, library)
    finally:
        os.close(fd)


def test_apply_plan_keeps_no_descriptor_open_after_a_refusal(
    tmp_path: Path, small_lib: Path
) -> None:
    row = PlanRow("sub/a.jpg", Action.KEEP, 0, 1, None, 0.0, "x", 0, 0, "")
    before = fd_count()
    with pytest.raises(UnsafePathError):
        apply_plan([row], small_lib, small_lib / "sub")
    assert fd_count() == before


# --- rare paths ---------------------------------------------------------------------------------


def test_a_folder_made_by_someone_else_in_the_meantime_is_used(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    real_mkdir = os.mkdir

    def raced(name, mode=0o777, *, dir_fd=None):
        real_mkdir(name, mode, dir_fd=dir_fd)
        raise FileExistsError(name)

    monkeypatch.setattr(os, "mkdir", raced)
    os.close(confine.open_folder(tmp_path.resolve() / "new", create=True, last_mode=0o750))
    assert (tmp_path / "new").is_dir()


@pytest.mark.parametrize(
    ("code", "outcome"), [(errno.EPERM, "tolerated"), (errno.EIO, "raised")], ids=["perm", "io"]
)
def test_a_filesystem_that_refuses_chmod_still_gets_the_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, code: int, outcome: str
) -> None:
    def refuse(*_args) -> None:
        raise OSError(code, "refused")

    monkeypatch.setattr(os, "fchmod", refuse)
    before = fd_count()
    target = tmp_path.resolve() / "new"
    if outcome == "tolerated":
        os.close(confine.open_folder(target, create=True, last_mode=0o750))
    else:
        with pytest.raises(OSError, match="refused"):
            confine.open_folder(target, create=True, last_mode=0o750)
    assert fd_count() == before


def test_a_folder_nested_beyond_the_depth_limit_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "a" / "b" / "c").mkdir(parents=True)
    monkeypatch.setattr(confine, "MAX_DEPTH", 2)
    fd = os.open(tmp_path / "a" / "b" / "c", os.O_RDONLY | os.O_DIRECTORY)
    before = fd_count()
    try:
        with pytest.raises(UnsafePathError, match="too deeply"):
            confine.refuse_inside(fd, os.stat(tmp_path.parent))
    finally:
        os.close(fd)
    assert fd_count() == before - 1


def test_a_plan_path_that_keeps_changing_is_given_up_on(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, small_lib: Path
) -> None:
    def appears(*_args) -> None:
        raise FileExistsError("appeared meanwhile")

    monkeypatch.setattr(fdio, "link_new", appears)
    plan = tmp_path / "plan.csv"
    assert (
        main(["library", "check", str(small_lib), "--plan", str(plan), "--jobs", "1"]) == EXIT_USAGE
    )
    assert not plan.exists()
    assert sorted(path.name for path in tmp_path.iterdir()) == ["lib"]
