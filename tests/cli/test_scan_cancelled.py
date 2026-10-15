"""``ffscan scan`` when the session reports a cancel: an interrupt, with the raw pages kept."""

import pytest

from fastfoto_linux.cli import cmd_scan, main
from fastfoto_linux.pipeline.process import ProcessResult
from tests.process_helpers import plain_sheet

FAST = ["--no-orient", "--no-restore"]


def test_a_cancelled_run_is_exit_130_with_the_raw_pages_kept(
    out, transport, capsys, monkeypatch
) -> None:
    transport.sheets = [plain_sheet()]
    monkeypatch.setattr(
        cmd_scan, "process_pages", lambda pages, settings: ProcessResult(cancelled=True)
    )
    assert main(["scan", "--out", str(out), *FAST, "--discard-raw"]) == 130
    captured = capsys.readouterr()
    assert "interrupted" in captured.err
    assert "raw pages kept in" in captured.err
    assert len(list((out / ".raw").iterdir())) == 1


@pytest.mark.parametrize("flag", ["--keep-raw", "--discard-raw"])
def test_a_cancelled_run_is_never_reported_as_a_clean_one(
    out, transport, capsys, monkeypatch, flag
) -> None:
    transport.sheets = [plain_sheet()]
    monkeypatch.setattr(
        cmd_scan, "process_pages", lambda pages, settings: ProcessResult(cancelled=True)
    )
    assert main(["scan", "--out", str(out), *FAST, flag]) == 130
    assert "raw pages kept in:" not in capsys.readouterr().out
