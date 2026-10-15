"""A bind mount of a library subfolder is the library: nothing may be written through it.

Walking ``..`` from a bind-mount root leaves the library's tree, so a destination (or plan folder)
that is a bind mount of ``SRC/sub`` looks unrelated by path. The identity (device and inode) of
every folder below the library is collected instead, and the destination, the plan's folder and
everything above them must be none of them.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from fastfoto_linux.cli.app import main
from fastfoto_linux.library import confine, fdio, safety
from fastfoto_linux.library.apply import STATUS_FAILED, apply_plan
from fastfoto_linux.library.plan import write_plan
from fastfoto_linux.library.safety import Library, UnsafePathError
from fastfoto_linux.library.walk import walk_library
from tests.library.apply_helpers import jpeg
from tests.library.jpeg_helpers import rotate_row, tree_snapshot, write_file

EXIT_USAGE = 2
UNSHARE_SECONDS = 60
RUNNER = "import sys; from fastfoto_linux.cli.app import main; sys.exit(main(sys.argv[1:]))"
MOUNT_AND_RUN = 'set -e; mount --bind "$1" "$2"; shift 2; exec "$@"'


def ident(path: Path) -> tuple[int, int]:
    info = os.stat(path)
    return (info.st_dev, info.st_ino)


def touch(root: Path, relative: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")


def alias_as(monkeypatch: pytest.MonkeyPatch, folder: Path, as_folder: Path) -> None:
    """Make ``folder`` look, by device and inode, like ``as_folder`` (what a bind mount does)."""
    real = safety.folder_id
    source, target = real(os.stat(folder)), real(os.stat(as_folder))
    monkeypatch.setattr(
        safety, "folder_id", lambda info: target if real(info) == source else real(info)
    )


@pytest.fixture
def library(tmp_path: Path) -> Path:
    root = tmp_path / "lib"
    write_file(root, "sub/a.jpg", jpeg(None))
    write_file(root, "album/b.jpg", jpeg(6))
    return root


# --- the walk collects the identities -----------------------------------------------------------


def test_the_walk_collects_the_identity_of_every_folder_including_skipped_ones(
    tmp_path: Path,
) -> None:
    library, outside = tmp_path / "lib", tmp_path / "outside"
    for name in ("a.jpg", "sub/deep/b.jpg", ".hidden/inner/c.jpg", "album/@eaDir/more/d.jpg"):
        touch(library, name)
    outside.mkdir()
    (library / "link").symlink_to(outside, target_is_directory=True)
    walked = walk_library(library).folders
    for folder in (".", "sub", "sub/deep", ".hidden", ".hidden/inner", "album/@eaDir/more"):
        assert ident(library / folder) in walked, folder
    assert ident(outside) not in walked
    assert walk_library(library).jpegs == ("a.jpg", "sub/deep/b.jpg")  # the listing is unchanged


# --- the checks use the identities ---------------------------------------------------------------


def open_folder_fd(path: Path) -> int:
    return os.open(path, os.O_RDONLY | os.O_DIRECTORY)


def test_refuse_inside_refuses_a_folder_whose_identity_is_in_the_set(tmp_path: Path) -> None:
    (tmp_path / "lib").mkdir()
    (tmp_path / "bound" / "deep").mkdir(parents=True)
    (tmp_path / "unrelated").mkdir()
    library = Library(os.stat(tmp_path / "lib"), frozenset({ident(tmp_path / "bound")}))
    for refused in (tmp_path / "bound", tmp_path / "bound" / "deep"):  # itself and one level above
        fd = open_folder_fd(refused)
        try:
            with pytest.raises(UnsafePathError):
                confine.refuse_inside(fd, library)
        finally:
            os.close(fd)
    fd = open_folder_fd(tmp_path / "unrelated")
    try:
        confine.refuse_inside(fd, library)
    finally:
        os.close(fd)


def test_every_folder_entered_below_the_destination_is_checked_against_the_set(
    tmp_path: Path, library: Path
) -> None:
    """A library subfolder bind-mounted at DEST/album is not a path under the library either."""
    dest = tmp_path / "dest"
    (dest / "album").mkdir(parents=True)
    row = rotate_row(library, "album/b.jpg", 90, 6, 3)
    source = fdio.read_regular(library / "album" / "b.jpg")
    root = Library(os.stat(library), frozenset({ident(dest / "album")}))
    root_fd = fdio.open_root(dest, root)
    try:
        with pytest.raises(UnsafePathError):
            fdio.publish(root_fd, row.path, b"new content", source, root)
    finally:
        os.close(root_fd)
    assert list((dest / "album").iterdir()) == []


# --- simulated bind mounts (always run) -----------------------------------------------------------


@pytest.mark.parametrize("which", ["folder", "parent"])
def test_fix_refuses_a_destination_that_is_a_library_folder_by_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, library: Path, which: str
) -> None:
    parent = tmp_path / "parent"
    dest = parent / "dest"
    dest.mkdir(parents=True)
    alias_as(monkeypatch, dest if which == "folder" else parent, library / "sub")
    plan = tmp_path / "plan.csv"
    write_plan(plan, (rotate_row(library, "sub/a.jpg", 90, 1, 6),))
    before = tree_snapshot(library)
    argv = ["library", "fix", str(plan), "--source", str(library), "--out", str(dest)]
    assert main(argv) == EXIT_USAGE
    assert tree_snapshot(library) == before
    assert list(dest.iterdir()) == []


def test_fix_mkdir_makes_nothing_below_a_folder_that_is_a_library_folder_by_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, library: Path
) -> None:
    parent = tmp_path / "parent"
    parent.mkdir()
    alias_as(monkeypatch, parent, library / "sub")
    plan = tmp_path / "plan.csv"
    write_plan(plan, (rotate_row(library, "sub/a.jpg", 90, 1, 6),))
    argv = ["library", "fix", str(plan), "--source", str(library), "--out", str(parent / "new")]
    assert main([*argv, "--mkdir"]) == EXIT_USAGE
    assert not (parent / "new").exists()


def test_a_folder_below_the_destination_that_is_a_library_folder_is_not_written_to(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, library: Path
) -> None:
    dest = tmp_path / "dest"
    (dest / "album").mkdir(parents=True)
    alias_as(monkeypatch, dest / "album", library / "album")
    before = tree_snapshot(library)
    result = apply_plan([rotate_row(library, "album/b.jpg", 90, 6, 3)], library, dest)
    assert [(o.status, o.reason) for o in result.outcomes] == [
        (STATUS_FAILED, "unsafe-destination")
    ]
    assert tree_snapshot(library) == before
    assert list((dest / "album").iterdir()) == []


@pytest.mark.parametrize("which", ["folder", "parent"])
def test_check_refuses_a_plan_folder_that_is_a_library_folder_by_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, library: Path, which: str
) -> None:
    parent = tmp_path / "parent"
    out = parent / "out"
    out.mkdir(parents=True)
    alias_as(monkeypatch, out if which == "folder" else parent, library / "sub")
    before = tree_snapshot(library)
    argv = ["library", "check", str(library), "--plan", str(out / "plan.csv"), "--jobs", "1"]
    assert main(argv) == EXIT_USAGE
    assert tree_snapshot(library) == before
    assert list(out.iterdir()) == []  # not even a staging file


# --- a real bind mount (needs unprivileged user namespaces) -------------------------------------


def run_in_namespace(
    source: Path, bound: Path, argv: list[str], cwd: Path
) -> subprocess.CompletedProcess[str]:
    """``ffscan argv`` in a new mount namespace where ``source`` is bind-mounted at ``bound``."""
    command = [
        *("unshare", "-Urm", "sh", "-c", MOUNT_AND_RUN, "sh", str(source), str(bound)),
        *(sys.executable, "-c", RUNNER, *argv),
    ]
    return subprocess.run(
        command, cwd=cwd, capture_output=True, text=True, timeout=UNSHARE_SECONDS, check=False
    )


@pytest.fixture
def bind_mounts_work(tmp_path: Path) -> None:
    probe = tmp_path / "probe"
    (probe / "a").mkdir(parents=True)
    (probe / "b").mkdir()
    try:
        done = run_in_namespace(probe / "a", probe / "b", ["--help"], tmp_path)
    except (OSError, subprocess.TimeoutExpired) as error:
        pytest.skip(f"cannot start a mount namespace here ({type(error).__name__})")
    if done.returncode != 0 or "usage" not in done.stdout.lower():
        pytest.skip("unprivileged user namespaces with bind mounts are not available here")


@pytest.mark.timeout(240)
@pytest.mark.parametrize("command", ["fix", "fix-mkdir", "check"])
def test_a_real_bind_mount_of_a_library_subfolder_is_refused(
    tmp_path: Path, library: Path, bind_mounts_work: None, command: str
) -> None:
    bound = tmp_path / "bound"
    bound.mkdir()
    plan = tmp_path / "plan.csv"
    write_plan(plan, (rotate_row(library, "sub/a.jpg", 90, 1, 6),))
    new = bound / "new"
    argvs = {
        "fix": ["fix", str(plan), "--source", str(library), "--out", str(bound)],
        "fix-mkdir": ["fix", str(plan), "--source", str(library), "--out", str(new), "--mkdir"],
        "check": ["check", str(library), "--plan", str(bound / "plan.csv"), "--jobs", "1"],
    }
    before = tree_snapshot(library)
    done = run_in_namespace(library / "sub", bound, ["library", *argvs[command]], tmp_path)
    assert done.returncode == EXIT_USAGE, done.stderr
    assert tree_snapshot(library) == before
