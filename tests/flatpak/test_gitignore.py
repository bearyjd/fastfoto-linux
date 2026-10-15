"""What the README's build commands leave in the checkout stays out of git."""

import shutil
import subprocess

import pytest

from tests.flatpak.helpers import ROOT

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def ignored(path: str) -> bool:
    """True when git ignores ``path`` (checked without needing the file to exist)."""
    inside = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if inside.returncode != 0:
        pytest.skip("not inside a git work tree (a source archive)")
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--quiet", path],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    assert result.returncode in (0, 1), result.stderr
    return result.returncode == 0


@pytest.mark.parametrize(
    "path",
    [
        "build-dir/files/bin/fastfoto",  # flatpak-builder ... build-dir
        "repo/summary",  # --repo=repo
        ".flatpak-builder/cache/objects",  # the builder's state folder
        "fastfoto-linux.flatpak",  # flatpak build-bundle
        "io.github.bearyjd.FastFotoLinux.flatpak",  # the CI job's bundle name
    ],
)
def test_the_files_of_a_local_flatpak_build_are_ignored(path: str) -> None:
    assert ignored(path)


@pytest.mark.parametrize(
    "path",
    [
        "packaging/flatpak/python-deps.json",
        "packaging/flatpak/io.github.bearyjd.FastFotoLinux.yml",
        "src/fastfoto_linux/repo/x.py",  # the folders are ignored at the top level only
        "tools/flatpak/gen_wheel_sources.py",
        "tests/flatpak/helpers.py",
    ],
)
def test_the_packaging_sources_are_not_ignored(path: str) -> None:
    assert not ignored(path)
