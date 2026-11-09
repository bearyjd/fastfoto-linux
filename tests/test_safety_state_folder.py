"""The scanner safety state keeps the legacy folder name through the rename.

A crash note written by a build from before the rename must still be found: moving the folder
would hide it and let a scanner command run without the required recovery.
"""

from pathlib import Path

import pytest

from fastfoto_linux.scanner import recovery, unclean


@pytest.fixture(autouse=True)
def state_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    return tmp_path


def test_the_unclean_note_stays_in_the_legacy_folder(state_home: Path) -> None:
    assert unclean.marker_path().parent == state_home / "fastfoto-linux"


def test_the_recovery_markers_stay_in_the_legacy_folder(state_home: Path) -> None:
    assert recovery._directory() == state_home / "fastfoto-linux" / "scanner-maintenance-recovery"
