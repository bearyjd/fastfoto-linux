"""``main``: argument handling, logging set-up and error mapping shared by every command."""

import logging
import tomllib
from pathlib import Path

from fastfoto_linux.cli import main
from tests.cli.fakes import write_dummy_page
from tests.process_helpers import plain_sheet, write_sheets

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"
FAST = ["--no-orient", "--no-restore"]


def test_ffscan_is_a_console_script() -> None:
    scripts = tomllib.loads(PYPROJECT.read_text())["project"]["scripts"]
    assert scripts["ffscan"] == "fastfoto_linux.cli:main"


def test_no_command_is_a_usage_error(capsys) -> None:
    assert main([]) == 2
    assert "usage" in capsys.readouterr().err.lower()


def test_help_exits_zero_and_names_the_commands(capsys) -> None:
    assert main(["--help"]) == 0
    out = capsys.readouterr().out
    assert all(command in out for command in ("devices", "scan", "process"))


def test_an_unknown_command_is_a_usage_error() -> None:
    assert main(["frobnicate"]) == 2


def test_an_unexpected_error_is_one_line_exit_1(tmp_path, out, monkeypatch, capsys) -> None:
    page = write_dummy_page(tmp_path / "raw", "page-1.png")

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("fastfoto_linux.cli.cmd_process.process_pages", boom)
    assert main(["process", str(page), "--out", str(out)]) == 1
    err = capsys.readouterr().err
    assert err.strip().splitlines() == ["ffscan: error: boom"]


def test_debug_adds_the_traceback(tmp_path, out, monkeypatch, capsys) -> None:
    page = write_dummy_page(tmp_path / "raw", "page-1.png")

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("fastfoto_linux.cli.cmd_process.process_pages", boom)
    assert main(["process", str(page), "--out", str(out), "--debug"]) == 1
    assert "Traceback" in capsys.readouterr().err


def _run_process(tmp_path: Path, out: Path, *extra: str) -> None:
    pages = write_sheets(tmp_path / "raw", [plain_sheet()])
    assert main(["process", *map(str, pages), "--out", str(out), *FAST, *extra]) == 0


def test_progress_shows_on_stderr_only_with_verbose(tmp_path, out, capsys) -> None:
    _run_process(tmp_path, out)
    quiet = capsys.readouterr().err
    (tmp_path / "raw2").mkdir()
    pages = write_sheets(tmp_path / "raw2", [plain_sheet()])
    assert main(["process", *map(str, pages), "--out", str(out), *FAST, "-v"]) == 0
    assert "wrote" not in quiet
    assert "wrote" in capsys.readouterr().err


def test_debug_logging_is_more_detailed_than_verbose(tmp_path, out, capsys) -> None:
    pages = write_sheets(tmp_path / "raw", [plain_sheet()])
    assert main(["process", *map(str, pages), "--out", str(out), *FAST, "-v"]) == 0
    verbose = capsys.readouterr().err
    assert main(["process", *map(str, pages), "--out", str(out), *FAST, "--debug"]) == 0
    assert len(capsys.readouterr().err) > len(verbose)


def test_main_leaves_the_logging_set_up_as_it_found_it(tmp_path, out) -> None:
    package = logging.getLogger("fastfoto_linux")
    handlers, level = list(package.handlers), package.level
    for _ in range(2):
        pages = write_sheets(tmp_path / f"raw{_}", [plain_sheet()])
        assert main(["process", *map(str, pages), "--out", str(out), *FAST, "--debug"]) == 0
    assert package.handlers == handlers
    assert package.level == level
