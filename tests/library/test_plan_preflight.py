"""A plan that cannot be written is refused before the scan, not hours into it."""

import os
from pathlib import Path

import pytest

from fastfoto_linux.cli import cmd_library
from fastfoto_linux.cli.app import main
from fastfoto_linux.library.planout import open_plan_target
from fastfoto_linux.library.safety import UnsafePathError
from tests.library.apply_helpers import jpeg
from tests.library.jpeg_helpers import write_file

EXIT_USAGE = 2
NAME_MAX = 255
LONG_NAME = "p" * (NAME_MAX - len(".csv")) + ".csv"  # a legal name; its staging name is not


@pytest.fixture
def library(tmp_path: Path) -> Path:
    root = tmp_path / "lib"
    write_file(root, "a.jpg", jpeg(None))
    return root


@pytest.fixture
def no_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    def scan(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("the scan started although the plan cannot be written")

    monkeypatch.setattr(cmd_library, "decide_files", scan)


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write to any folder")
def test_a_read_only_plan_folder_is_refused_before_the_scan(
    tmp_path: Path, library: Path, no_scan: None, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "out"
    out.mkdir()
    out.chmod(0o500)
    try:
        code = main(["library", "check", str(library), "--plan", str(out / "plan.csv")])
    finally:
        out.chmod(0o700)
    assert code == EXIT_USAGE
    assert "plan" in capsys.readouterr().err
    assert list(out.iterdir()) == []


def test_a_plan_name_that_is_too_long_for_its_staging_file_is_refused_before_the_scan(
    tmp_path: Path, library: Path, no_scan: None
) -> None:
    out = tmp_path / "out"
    out.mkdir()
    code = main(["library", "check", str(library), "--plan", str(out / LONG_NAME)])
    assert code == EXIT_USAGE
    assert list(out.iterdir()) == []


def test_opening_the_target_leaves_nothing_behind(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    with open_plan_target(out / "plan.csv"):
        pass
    assert list(out.iterdir()) == []


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write to any folder")
def test_the_target_refuses_a_folder_it_cannot_write_to(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    out.chmod(0o500)
    try:
        with pytest.raises(UnsafePathError, match="plan"), open_plan_target(out / "plan.csv"):
            pass
    finally:
        out.chmod(0o700)
