"""``ffscan scan`` with a faked transport: the real scanner is never started."""

from pathlib import Path

import pytest

from fastfoto_linux.cli import main
from fastfoto_linux.scanner import (
    NoDocumentsError,
    ScanError,
    ScannerNotFoundError,
    ShimMissingError,
    Source,
)
from fastfoto_linux.session import raw as rawdir
from tests._output_helpers import names
from tests.cli.fakes import DEVICE, HOST
from tests.process_helpers import page_name, plain_sheet, written_sheet

FAST = ["--no-orient", "--no-restore"]
STAMP = "20261013T230000Z"


@pytest.fixture(autouse=True)
def fixed_stamp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rawdir, "utc_stamp", lambda: STAMP)


def scan(out: Path, *extra: str) -> int:
    """``ffscan scan`` that discards its raw pages unless a test is about them (test_scan_raw)."""
    raw_option = [] if {"--keep-raw", "--discard-raw"} & set(extra) else ["--discard-raw"]
    return main(["scan", "--out", str(out), *FAST, *raw_option, *extra])


def test_scan_processes_the_pages_and_leaves_no_raw_files(out, transport, capsys) -> None:
    transport.sheets = [plain_sheet(0), written_sheet(1)]
    assert scan(out) == 0
    assert names(out) == [
        "FastFoto_0001.jpg",
        "FastFoto_0002.jpg",
        "FastFoto_0002_b.jpg",
    ]
    stdout = capsys.readouterr().out
    assert "photos written: 2" in stdout
    assert "backs kept: 1" in stdout
    (job,) = transport.jobs
    assert job.device == DEVICE
    assert job.source is Source.DUPLEX
    assert job.resolution == 600
    assert job.output_dir.is_relative_to(out)
    assert not job.output_dir.exists()


def test_the_scanner_environment_comes_from_the_target(out, transport, monkeypatch) -> None:
    monkeypatch.setenv("FASTFOTO_TEST_MARKER", "1")
    transport.sheets = [plain_sheet()]
    assert scan(out) == 0
    assert transport.envs[0]["FASTFOTO_TEST_MARKER"] == "1"


def test_simplex_scans_the_front_only_and_every_page_is_a_photo(out, transport) -> None:
    transport.front_pages = 2
    assert scan(out, "--simplex", "--dpi", "300") == 0
    (job,) = transport.jobs
    assert job.source is Source.FRONT
    assert job.resolution == 300
    assert names(out) == ["FastFoto_0001.jpg", "FastFoto_0002.jpg"]


def test_keep_raw_keeps_the_pages_under_dot_raw(out, transport, capsys) -> None:
    transport.sheets = [plain_sheet(0), plain_sheet(1)]
    assert scan(out, "--keep-raw") == 0
    kept = out / ".raw" / STAMP
    assert sorted(p.name for p in kept.iterdir()) == [page_name(n) for n in (1, 2, 3, 4)]
    assert transport.jobs[0].output_dir == kept
    assert str(kept) in capsys.readouterr().out


def test_a_failed_sheet_is_reported_exit_1_and_its_raw_pages_are_kept(
    out, transport, capsys
) -> None:
    transport.sheets = [plain_sheet(0), plain_sheet(1), plain_sheet(2)]
    transport.corrupt_page = (3, 4)  # both pages: with one readable page the sheet is saved whole
    assert scan(out) == 1
    assert [n for n in names(out) if n.endswith(".jpg")] == [
        "FastFoto_0001.jpg",
        "FastFoto_0002.jpg",
    ]
    err = capsys.readouterr().err
    assert page_name(3) in err
    assert page_name(4) in err
    kept = out / ".raw" / STAMP
    assert (kept / page_name(3)).exists()
    assert str(kept) in err


def test_pages_scanned_before_a_scanner_failure_are_still_processed(out, transport, capsys) -> None:
    transport.sheets = [plain_sheet(0), plain_sheet(1), plain_sheet(2)]
    transport.pages_before_failure = 4
    transport.failure = lambda pages: ScanError("paper jam", returncode=1, pages=pages)
    assert scan(out) == 1
    assert [n for n in names(out) if n.endswith(".jpg")] == [
        "FastFoto_0001.jpg",
        "FastFoto_0002.jpg",
    ]
    assert "paper jam" in capsys.readouterr().err


def test_a_scanner_failure_before_any_page_leaves_nothing(out, transport, capsys) -> None:
    transport.failure = lambda pages: ScanError("could not start scanimage", pages=pages)
    assert scan(out) == 1
    assert names(out) == []
    assert "could not start scanimage" in capsys.readouterr().err


def test_a_scanner_failure_with_no_pages_reported_loses_no_file_found_on_disk(
    out, transport, capsys
) -> None:
    transport.sheets = [plain_sheet()]
    transport.failure = lambda pages: ScanError("could not start scanimage", pages=pages)
    assert scan(out) == 1
    kept = out / ".raw" / STAMP
    assert sorted(p.name for p in kept.iterdir()) == [page_name(1), page_name(2)]
    assert [n for n in names(out) if n.endswith(".jpg")] == []
    assert str(kept) in capsys.readouterr().err


def test_scanner_not_found_is_exit_3(out, transport, capsys) -> None:
    transport.resolve_error = ScannerNotFoundError("no FF-680W found on USB")
    assert scan(out) == 3
    err = capsys.readouterr().err
    assert "no FF-680W found" in err
    assert "Traceback" not in err
    assert len(err.strip().splitlines()) == 1
    assert transport.jobs == []


def test_a_missing_shim_is_exit_3_and_names_the_build_command(out, transport, capsys) -> None:
    transport.resolve_error = ShimMissingError("build it with `make -C tools/usb-gap-shim`")
    assert scan(out) == 3
    assert "make -C tools/usb-gap-shim" in capsys.readouterr().err


def test_an_empty_feeder_is_exit_4_and_leaves_nothing(out, transport, capsys) -> None:
    transport.failure = lambda pages: NoDocumentsError("the document feeder is empty")
    assert scan(out) == 4
    assert names(out) == []
    err = capsys.readouterr().err
    assert "feeder is empty" in err
    assert len(err.strip().splitlines()) == 1


def test_ctrl_c_stops_cleanly_with_the_shell_convention(out, transport, capsys) -> None:
    transport.failure = lambda pages: KeyboardInterrupt()
    assert scan(out) == 130
    assert names(out) == []
    assert "interrupted" in capsys.readouterr().err


@pytest.mark.parametrize("debug", [False, True])
def test_a_traceback_is_shown_only_with_debug(out, transport, capsys, debug) -> None:
    transport.failure = lambda pages: NoDocumentsError("the document feeder is empty")
    assert scan(out, *(["--debug"] if debug else [])) == 4
    assert ("Traceback" in capsys.readouterr().err) is debug


def test_a_network_scanner_gets_a_private_config_dir_that_is_removed(out, transport) -> None:
    transport.sheets = [plain_sheet()]
    assert scan(out, "--net", HOST) == 0
    (call,) = transport.resolve_calls
    assert call["net_host"] == HOST
    assert transport.config_dir_existed == [True]
    assert not Path(call["config_dir"]).exists()


def test_without_a_network_host_no_config_dir_is_made(out, transport) -> None:
    transport.sheets = [plain_sheet()]
    assert scan(out) == 0
    (call,) = transport.resolve_calls
    assert call["net_host"] is None
    assert call.get("config_dir") is None


BAD_ARGUMENTS = [
    ["--dpi", "123"],
    ["--date", "1975-13"],
    ["--date", "abc"],
    ["--quality", "0"],
    ["--quality", "101"],
    ["--quality", "high"],
    ["--album", "///"],
    ["--prefix", ".."],
    ["--notes", "x" * 10_001],
    ["--backs", "sometimes"],
    ["--feed", "sideways"],
    ["--net", "not a host"],
    ["--keep-original", "--enhanced-only"],
    ["--keep-raw", "--discard-raw"],
]


@pytest.mark.parametrize("bad", BAD_ARGUMENTS, ids=lambda bad: bad[0] + str(len(bad)))
def test_bad_input_is_exit_2_before_the_scanner_is_touched(out, transport, capsys, bad) -> None:
    assert scan(out, *bad) == 2
    assert transport.resolve_calls == []
    assert transport.jobs == []
    assert "Traceback" not in capsys.readouterr().err


def test_a_missing_output_folder_is_exit_2_unless_mkdir_is_given(
    tmp_path, transport, capsys
) -> None:
    transport.sheets = [plain_sheet()]
    target = tmp_path / "new" / "album-root"
    assert scan(target) == 2
    assert not target.exists()
    assert transport.jobs == []
    assert "--mkdir" in capsys.readouterr().err
    assert scan(target, "--mkdir") == 0
    assert names(target) == ["FastFoto_0001.jpg"]


def test_the_output_option_is_required(transport, capsys) -> None:
    assert main(["scan", *FAST]) == 2
    assert "--out" in capsys.readouterr().err


def test_progress_is_logged_page_by_page_with_verbose(out, transport, capsys) -> None:
    transport.sheets = [plain_sheet()]
    assert scan(out, "-v") == 0
    err = capsys.readouterr().err
    assert "page 1 scanned" in err
    assert "page 2 scanned" in err
