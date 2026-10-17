"""A private raw folder is never a link: chmod would change the mode of whatever it points to."""

import os
import stat
from pathlib import Path

import pytest

from fastfoto_linux.session.raw import create_raw_dir
from tests.session.conftest import STAMP


def mode_of(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@pytest.fixture
def target(tmp_path: Path) -> Path:
    folder = tmp_path / "elsewhere"
    folder.mkdir(mode=0o755)
    folder.chmod(0o755)
    return folder


@pytest.fixture
def linked(out: Path, target: Path) -> Path:
    """``out/.raw/<stamp>`` as a link to a folder somewhere else."""
    (out / ".raw").mkdir()
    link = out / ".raw" / STAMP
    link.symlink_to(target, target_is_directory=True)
    return link


def test_a_linked_private_folder_is_refused(out: Path, linked: Path) -> None:
    with pytest.raises(OSError, match=STAMP):
        create_raw_dir(out, keep=True, private=True)


def test_what_the_link_points_to_keeps_its_mode(out: Path, linked: Path, target: Path) -> None:
    with pytest.raises(OSError, match=STAMP):
        create_raw_dir(out, keep=True, private=True)
    assert mode_of(target) == 0o755
    assert list(target.iterdir()) == []


def test_a_link_to_a_missing_folder_is_refused_too(out: Path, tmp_path: Path) -> None:
    (out / ".raw").mkdir()
    (out / ".raw" / STAMP).symlink_to(tmp_path / "nowhere", target_is_directory=True)
    with pytest.raises(OSError, match=STAMP):
        create_raw_dir(out, keep=True, private=True)


def test_a_folder_that_is_really_a_folder_is_still_made_private(out: Path) -> None:
    (out / ".raw" / STAMP).mkdir(parents=True, mode=0o755)
    old = os.umask(0o022)
    try:
        folder = create_raw_dir(out, keep=True, private=True)
    finally:
        os.umask(old)
    assert folder == out / ".raw" / STAMP
    assert mode_of(folder) == 0o700
