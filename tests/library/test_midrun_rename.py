"""A folder renamed into the library while a run is going is refused again just before publishing.

The destination and the plan's folder are opened and checked once; hours can pass before a file is
published. Right before each publish (and before the staging file is made) the held descriptor is
checked against the library again, so a folder moved into it meanwhile gets nothing.
"""

import os
from pathlib import Path

import pytest

from fastfoto_linux.cli import cmd_library
from fastfoto_linux.cli.app import main
from fastfoto_linux.library import fdio
from fastfoto_linux.library.apply import STATUS_FAILED, apply_plan
from fastfoto_linux.library.plan import write_plan
from tests.library.apply_helpers import jpeg
from tests.library.jpeg_helpers import rotate_row, tree_snapshot, write_file

EXIT_USAGE = 2
MOVED = "moved-in"


@pytest.fixture
def library(tmp_path: Path) -> Path:
    root = tmp_path / "lib"
    write_file(root, "sub/a.jpg", jpeg(None))
    return root


def moves_into(folder: Path, library: Path) -> None:
    folder.rename(library / "sub" / MOVED)


def run_once(hook):
    """A function that calls ``hook`` the first time it is called and does nothing after."""
    done = []

    def once(*_args: object, **_kwargs: object) -> None:
        if not done:
            done.append(True)
            hook()

    return once


def expected_after(before: dict[str, str]) -> dict[str, str]:
    return {**before, f"sub/{MOVED}": "dir"}


# --- fix: the destination -----------------------------------------------------------------------


def fix_outcome(library: Path, dest: Path) -> list[tuple[str, str]]:
    row = rotate_row(library, "sub/a.jpg", 90, 1, 6)
    result = apply_plan([row], library, dest)
    return [(outcome.status, outcome.reason) for outcome in result.outcomes]


def test_a_destination_moved_into_the_library_before_a_file_is_published_gets_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, library: Path, dest: Path
) -> None:
    real = fdio._publish_in
    hook = run_once(lambda: moves_into(dest, library))

    def moved_first(*args, **kwargs):
        hook()
        return real(*args, **kwargs)

    monkeypatch.setattr(fdio, "_publish_in", moved_first)
    before = tree_snapshot(library)
    assert fix_outcome(library, dest) == [(STATUS_FAILED, "unsafe-destination")]
    assert tree_snapshot(library) == expected_after(before)


def test_a_destination_moved_into_the_library_while_the_copy_is_staged_gets_no_copy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, library: Path, dest: Path
) -> None:
    """The first fsync is the staged copy's, just before it is linked into place."""
    real = os.fsync
    hook = run_once(lambda: moves_into(dest, library))

    def moved_after_staging(fd: int) -> None:
        real(fd)
        hook()

    monkeypatch.setattr(os, "fsync", moved_after_staging)
    before = tree_snapshot(library)
    assert fix_outcome(library, dest) == [(STATUS_FAILED, "unsafe-destination")]
    assert tree_snapshot(library) == expected_after(before)  # no copy, and no staging file left


# --- check: the plan ----------------------------------------------------------------------------


def scan_hook(monkeypatch: pytest.MonkeyPatch, hook) -> None:
    real = cmd_library.decide_files

    def scan(src, relatives, jobs):
        hook()
        return real(src, relatives, 1)

    monkeypatch.setattr(cmd_library, "decide_files", scan)


@pytest.mark.parametrize("older_plan", [False, True], ids=["new plan", "older plan"])
def test_a_plan_folder_moved_into_the_library_during_the_scan_gets_no_plan(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, library: Path, older_plan: bool
) -> None:
    out = tmp_path / "out"
    out.mkdir()
    if older_plan:
        write_plan(out / "plan.csv", ())
    scan_hook(monkeypatch, lambda: moves_into(out, library))
    before = tree_snapshot(library)
    argv = ["library", "check", str(library), "--plan", str(out / "plan.csv"), "--jobs", "1"]
    assert main(argv) == EXIT_USAGE
    after = tree_snapshot(library)
    assert set(after) - set(before) == {f"sub/{MOVED}"}  # the moved folder, and nothing in it
    assert not any(name.startswith(f"sub/{MOVED}/.") for name in after)  # no staging file
    if older_plan:
        assert "sub/a.jpg" not in (library / "sub" / MOVED / "plan.csv").read_text()


def test_a_plan_folder_moved_into_the_library_after_the_plan_was_staged_gets_no_plan(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, library: Path
) -> None:
    out = tmp_path / "out"
    out.mkdir()
    real = os.fsync
    hook = run_once(lambda: moves_into(out, library))

    def moved_after_staging(fd: int) -> None:
        real(fd)
        hook()

    monkeypatch.setattr(os, "fsync", moved_after_staging)
    before = tree_snapshot(library)
    argv = ["library", "check", str(library), "--plan", str(out / "plan.csv"), "--jobs", "1"]
    assert main(argv) == EXIT_USAGE
    assert tree_snapshot(library) == expected_after(before)
