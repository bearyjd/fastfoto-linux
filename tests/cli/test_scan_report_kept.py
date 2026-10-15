"""``ffscan scan`` says where the raw pages are even when the summary cannot be printed."""

from fastfoto_linux.cli import cmd_scan, main
from tests.process_helpers import plain_sheet

FAST = ["--no-orient", "--no-restore"]


def test_the_kept_folder_is_reported_when_printing_the_summary_fails(
    out, transport, capsys, monkeypatch
) -> None:
    def explode(result) -> None:
        raise RuntimeError("summary exploded")

    transport.sheets = [plain_sheet()]
    monkeypatch.setattr(cmd_scan, "print_summary", explode)
    assert main(["scan", "--out", str(out), *FAST, "--keep-raw"]) == 1
    captured = capsys.readouterr()
    assert "summary exploded" in captured.err
    assert "raw pages kept in" in captured.out + captured.err
    assert len(list((out / ".raw").iterdir())) == 1
