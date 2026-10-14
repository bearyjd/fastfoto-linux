"""``ffscan scan`` and its raw pages: when they are kept, what is said, what cannot hide them."""

import errno
from pathlib import Path

import pytest

from fastfoto_linux.cli import main, rawdir
from fastfoto_linux.scanner import ScanError
from tests._output_helpers import names
from tests.process_helpers import page_name, plain_sheet, written_sheet

FAST = ["--no-orient", "--no-restore"]
STAMP = "20261013T230000Z"
DROPPED = "backs dropped: {} (no writing detected; use --backs always to keep them)"
KEPT_FOR_DROPPED = (
    "raw pages kept in {} (a back was dropped); --discard-raw deletes them after a clean run"
)


@pytest.fixture(autouse=True)
def fixed_stamp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rawdir, "utc_stamp", lambda: STAMP)


def scan(out: Path, *extra: str) -> int:
    """``ffscan scan`` with the default raw page handling."""
    return main(["scan", "--out", str(out), *FAST, *extra])


def kept(out: Path) -> Path:
    return out / ".raw" / STAMP


def kept_pages(out: Path) -> list[str]:
    return sorted(p.name for p in kept(out).iterdir()) if kept(out).is_dir() else []


def photos(out: Path) -> list[str]:
    return [n for n in names(out) if n.endswith(".jpg")]


def all_pages(count: int) -> list[str]:
    return [page_name(n) for n in range(1, count + 1)]


# --- a scanner failure after a clean process -------------------------------------------------


def test_a_jam_after_three_pages_keeps_the_raw_pages_and_flags_the_orphan(
    out, transport, capsys
) -> None:
    transport.sheets = [plain_sheet(0), plain_sheet(1)]
    transport.keep_on_disk = 3
    transport.pages_before_failure = 3
    transport.failure = lambda pages: ScanError("paper jam", returncode=1, pages=pages)
    assert scan(out, "--discard-raw") == 1
    assert kept_pages(out) == all_pages(3)
    captured = capsys.readouterr()
    assert str(kept(out)) in captured.err
    assert "incomplete sheet" in captured.out
    assert page_name(3) in captured.out


# --- backs dropped by --backs auto -----------------------------------------------------------


def test_a_dropped_back_keeps_the_raw_pages_by_default_and_says_so(out, transport, capsys) -> None:
    transport.sheets = [plain_sheet(0), written_sheet(1)]
    assert scan(out) == 0
    assert kept_pages(out) == all_pages(4)
    stdout = capsys.readouterr().out
    assert DROPPED.format(1) in stdout
    assert page_name(1) in stdout
    assert KEPT_FOR_DROPPED.format(kept(out)) in stdout
    assert "disk space" in stdout


def test_keep_raw_does_not_blame_a_dropped_back_for_keeping_the_pages(
    out, transport, capsys
) -> None:
    transport.sheets = [plain_sheet(0), written_sheet(1)]
    assert scan(out, "--keep-raw") == 0
    stdout = capsys.readouterr().out
    assert f"raw pages kept in: {kept(out)}" in stdout
    assert "a back was dropped" not in stdout


def test_a_failed_delete_after_discard_raw_does_not_blame_a_dropped_back(
    out, transport, capsys, monkeypatch
) -> None:
    def refuse(folders):
        raise OSError(errno.EIO, "Input/output error")

    monkeypatch.setattr(rawdir, "sync_folders", refuse)
    transport.sheets = [plain_sheet(0), written_sheet(1)]
    assert scan(out, "--discard-raw") == 0
    stdout = capsys.readouterr().out
    assert "raw pages kept in" in stdout
    assert "a back was dropped" not in stdout
    assert DROPPED.format(1) in stdout


def test_discard_raw_deletes_the_pages_after_a_clean_run_but_still_reports_the_drop(
    out, transport, capsys
) -> None:
    transport.sheets = [plain_sheet(0), written_sheet(1)]
    assert scan(out, "--discard-raw") == 0
    assert not (out / ".raw").exists()
    stdout = capsys.readouterr().out
    assert DROPPED.format(1) in stdout
    assert "raw pages kept" not in stdout


def test_no_raw_pages_are_kept_when_every_back_was_kept(out, transport, capsys) -> None:
    transport.sheets = [written_sheet(0), written_sheet(1)]
    assert scan(out) == 0
    assert not (out / ".raw").exists()
    assert "backs dropped" not in capsys.readouterr().out


@pytest.mark.parametrize("policy", ["always", "never"])
def test_a_back_policy_set_by_the_user_does_not_keep_the_raw_pages(out, transport, policy) -> None:
    transport.sheets = [plain_sheet(0), plain_sheet(1)]
    assert scan(out, "--backs", policy) == 0
    assert not (out / ".raw").exists()
    assert [p.name for p in out.iterdir() if p.name.startswith(".ffscan-raw")] == []


def test_discard_raw_never_overrides_a_failed_sheet(out, transport, capsys) -> None:
    transport.sheets = [plain_sheet(0), plain_sheet(1), plain_sheet(2)]
    transport.corrupt_page = 3
    assert scan(out, "--discard-raw") == 1
    assert kept_pages(out) == all_pages(6)
    assert str(kept(out)) in capsys.readouterr().err


def test_discard_raw_never_overrides_a_scanner_error(out, transport) -> None:
    transport.sheets = [plain_sheet(0), plain_sheet(1)]
    transport.pages_before_failure = 4
    transport.failure = lambda pages: ScanError("paper jam", returncode=1, pages=pages)
    assert scan(out, "--discard-raw") == 1
    assert kept_pages(out) == all_pages(4)


def test_a_degraded_sheet_is_exit_1_and_keeps_the_raw_pages(
    out, transport, capsys, monkeypatch
) -> None:
    def boom(img, dpi):
        raise ValueError("restore exploded")

    monkeypatch.setattr("fastfoto_linux.cli.options.restore_colour", boom)
    transport.sheets = [plain_sheet()]
    assert main(["scan", "--out", str(out), "--no-orient", "--discard-raw"]) == 1
    assert photos(out) == ["FastFoto_0001.jpg"]
    assert kept_pages(out) == all_pages(2)
    assert str(kept(out)) in capsys.readouterr().err


# --- interrupts and crashes keep the pages ---------------------------------------------------


def test_ctrl_c_with_pages_on_disk_keeps_them_and_prints_the_path(out, transport, capsys) -> None:
    transport.sheets = [plain_sheet(0), plain_sheet(1)]
    transport.failure = lambda pages: KeyboardInterrupt()
    assert scan(out, "--discard-raw") == 130
    assert photos(out) == []
    assert kept_pages(out) == all_pages(4)
    err = capsys.readouterr().err
    assert "interrupted" in err
    assert str(kept(out)) in err


def test_an_exception_while_processing_keeps_the_raw_pages(
    out, transport, capsys, monkeypatch
) -> None:
    def boom(pages, settings):
        raise RuntimeError("processing blew up")

    monkeypatch.setattr("fastfoto_linux.cli.cmd_scan.process_pages", boom)
    transport.sheets = [plain_sheet(0), plain_sheet(1)]
    assert scan(out, "--discard-raw") == 1
    assert kept_pages(out) == all_pages(4)
    err = capsys.readouterr().err
    assert "processing blew up" in err
    assert str(kept(out)) in err


def test_a_scanner_error_without_pages_still_keeps_files_found_on_disk(
    out, transport, capsys
) -> None:
    transport.sheets = [plain_sheet()]
    transport.pages_before_failure = 0
    transport.failure = lambda pages: ScanError("paper jam", returncode=1, pages=pages)
    assert scan(out, "--discard-raw") == 1
    assert photos(out) == []
    assert kept_pages(out) == all_pages(2)
    assert str(kept(out)) in capsys.readouterr().err


def test_a_failure_to_move_the_raw_pages_does_not_hide_the_real_error(
    out, transport, capsys, monkeypatch
) -> None:
    def boom(pages, settings):
        raise RuntimeError("processing blew up")

    monkeypatch.setattr("fastfoto_linux.cli.cmd_scan.process_pages", boom)
    (out / ".raw").write_text("a file where the kept pages should go")
    transport.sheets = [plain_sheet()]
    assert scan(out) == 1
    err = capsys.readouterr().err
    assert "processing blew up" in err
    (left_over,) = (p for p in out.iterdir() if p.name.startswith(rawdir.TEMP_PREFIX))
    assert str(left_over) in err
    assert sorted(p.name for p in left_over.iterdir()) == all_pages(2)


def test_a_raw_folder_that_cannot_be_listed_does_not_hide_the_real_error(
    out, transport, capsys, monkeypatch
) -> None:
    def boom(pages, settings):
        raise RuntimeError("processing blew up")

    real_iterdir = Path.iterdir

    def refuse_raw(self):
        if self.name.startswith(rawdir.TEMP_PREFIX):
            raise OSError(errno.EIO, "Input/output error")
        return real_iterdir(self)

    monkeypatch.setattr("fastfoto_linux.cli.cmd_scan.process_pages", boom)
    monkeypatch.setattr(Path, "iterdir", refuse_raw)
    transport.sheets = [plain_sheet()]
    assert scan(out) == 1
    err = capsys.readouterr().err
    assert "processing blew up" in err
    (left_over,) = (p for p in out.glob(f"{rawdir.TEMP_PREFIX}*"))
    assert str(left_over) in err
