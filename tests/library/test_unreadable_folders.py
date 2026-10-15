"""A library folder that cannot be listed leaves a hole in the bind-mount check, so it fails closed.

The identities (device and inode) of the library's folders come from walking it; a bind mount of a
folder the walk could not list (or of one inside it) is not among them. When any folder could not be
listed, hidden or not, a destination or plan folder on a device the library uses cannot be proven to
be outside it and is refused. One on another device (a bind mount shares the device of what it
mounts) stays allowed.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from fastfoto_linux.cli.app import main
from fastfoto_linux.library import safety
from fastfoto_linux.library.apply import STATUS_FAILED, apply_plan
from fastfoto_linux.library.plan import write_plan
from fastfoto_linux.library.walk import walk_library
from tests.library.apply_helpers import FIRST, jpeg
from tests.library.jpeg_helpers import rotate_row, tree_snapshot, write_file

pytestmark = pytest.mark.skipif(os.geteuid() == 0, reason="root can list every folder")

EXIT_USAGE = 2
EXPLANATION = "could not be read"
ADVICE = "another drive"
MODE_OPEN = 0o755
COUNTED = {"locked": 1, ".hidden": 0, "2001/@eaDir": 0}  # what the user-facing summary counts


@pytest.fixture(params=sorted(COUNTED))
def unlistable(request: pytest.FixtureRequest, lib: Path) -> Iterator[Path]:
    """A folder of the library that cannot be listed: a plain one, a hidden one, an ``@eaDir``."""
    folder = lib / request.param
    write_file(lib, f"{request.param}/inner.jpg", jpeg(1))
    folder.chmod(0)
    try:
        if os.access(folder, os.R_OK):
            pytest.skip("this account can list a folder without read permission")
        yield folder
    finally:
        folder.chmod(MODE_OPEN)


def on_another_device(monkeypatch: pytest.MonkeyPatch, *folders: Path) -> None:
    """Make ``folders`` look like they are on another device than they are (``alias_as`` style)."""
    real = safety.folder_id
    moved = {real(os.stat(folder)) for folder in folders}

    def folder_id(info: os.stat_result) -> tuple[int, int]:
        device, inode = real(info)
        return (device + 1, inode) if (device, inode) in moved else (device, inode)

    monkeypatch.setattr(safety, "folder_id", folder_id)


def check_argv(lib: Path, plan: Path) -> list[str]:
    return ["library", "check", str(lib), "--plan", str(plan), "--jobs", "1"]


def fix_argv(lib: Path, plan: Path, dest: Path) -> list[str]:
    return ["library", "fix", str(plan), "--source", str(lib), "--out", str(dest)]


@pytest.fixture
def out(tmp_path: Path) -> Path:
    path = tmp_path / "out"
    path.mkdir()
    return path


@pytest.fixture
def plan_file(tmp_path: Path, lib: Path) -> Path:
    plan = tmp_path / "plan.csv"
    write_plan(plan, (rotate_row(lib, FIRST, 90, 1, 6),))
    return plan


# --- the walk counts every folder it could not list -------------------------------------------


def test_the_walk_counts_every_unlistable_folder_but_the_summary_count_is_unchanged(
    lib: Path, unlistable: Path
) -> None:
    walked = walk_library(lib)
    assert walked.unlisted_folders == 1
    assert walked.unreadable_folders == COUNTED[unlistable.relative_to(lib).as_posix()]


def test_a_library_that_can_be_listed_has_no_unlistable_folders(lib: Path) -> None:
    assert walk_library(lib).unlisted_folders == 0


# --- check ------------------------------------------------------------------------------------


def test_check_refuses_a_plan_on_the_libraries_device_and_writes_nothing(
    lib: Path, unlistable: Path, out: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = tree_snapshot(lib)
    assert main(check_argv(lib, out / "plan.csv")) == EXIT_USAGE
    error = capsys.readouterr().err
    assert EXPLANATION in error
    assert ADVICE in error
    assert list(out.iterdir()) == []  # not even a staging file
    assert tree_snapshot(lib) == before


def test_check_allows_a_plan_on_another_device(
    monkeypatch: pytest.MonkeyPatch, lib: Path, unlistable: Path, out: Path
) -> None:
    on_another_device(monkeypatch, out)
    assert main(check_argv(lib, out / "plan.csv")) == 0
    assert (out / "plan.csv").is_file()


def test_check_is_unchanged_when_every_folder_can_be_listed(lib: Path, out: Path) -> None:
    assert main(check_argv(lib, out / "plan.csv")) == 0
    assert (out / "plan.csv").is_file()


# --- fix --------------------------------------------------------------------------------------


def test_fix_refuses_a_destination_on_the_libraries_device_and_writes_nothing(
    lib: Path,
    unlistable: Path,
    plan_file: Path,
    dest: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    before = tree_snapshot(lib)
    assert main(fix_argv(lib, plan_file, dest)) == EXIT_USAGE
    error = capsys.readouterr().err
    assert EXPLANATION in error
    assert ADVICE in error
    assert list(dest.iterdir()) == []  # no copy and no manifest
    assert tree_snapshot(lib) == before


def test_fix_mkdir_makes_nothing_on_the_libraries_device(
    lib: Path, unlistable: Path, plan_file: Path, tmp_path: Path
) -> None:
    new = tmp_path / "made" / "dest"
    assert main([*fix_argv(lib, plan_file, new), "--mkdir"]) == EXIT_USAGE
    assert not (tmp_path / "made").exists()


def test_fix_allows_a_destination_on_another_device(
    monkeypatch: pytest.MonkeyPatch, lib: Path, unlistable: Path, plan_file: Path, dest: Path
) -> None:
    (dest / "2001").mkdir()
    on_another_device(monkeypatch, dest, dest / "2001")
    assert main(fix_argv(lib, plan_file, dest)) == 0
    assert (dest / FIRST).is_file()


def test_fix_is_unchanged_when_every_folder_can_be_listed(
    lib: Path, plan_file: Path, dest: Path
) -> None:
    assert main(fix_argv(lib, plan_file, dest)) == 0
    assert (dest / FIRST).is_file()


def test_a_folder_below_the_destination_on_the_libraries_device_is_not_written_to(
    monkeypatch: pytest.MonkeyPatch, lib: Path, unlistable: Path, dest: Path
) -> None:
    """DEST is on another drive, but DEST/2001 is a bind mount of a folder on the library's."""
    (dest / "2001").mkdir()
    on_another_device(monkeypatch, dest)
    result = apply_plan([rotate_row(lib, FIRST, 90, 1, 6)], lib, dest)
    assert [(o.status, o.reason) for o in result.outcomes] == [
        (STATUS_FAILED, "unsafe-destination")
    ]
    assert list((dest / "2001").iterdir()) == []
