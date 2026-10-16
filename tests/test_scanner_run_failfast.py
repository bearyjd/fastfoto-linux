"""run_scan stops at once when scanimage reports a real error, and not at the normal batch end."""

import os
import signal
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from fastfoto_linux.scanner import run as run_module
from fastfoto_linux.scanner.errors import ScanError
from fastfoto_linux.scanner.job import ScanJob
from fastfoto_linux.scanner.run import run_scan
from fastfoto_linux.scanner.stderr_monitor import StderrMonitor
from tests._fake_scanimage import fake_env, install

DEVICE = "epsonds:libusb:001:002"
IO_ERROR = "scanimage: sane_start: Error during device I/O"
OUT_OF_DOCS = "scanimage: sane_start: Document feeder out of documents"
# What the app showed after the stuck scanner, verbatim (nothing private in it).
SCANIMAGE_SAID = [
    "Scanning infinity pages, incrementing by 1, numbering from 1",
    "Scanning page 1",
    IO_ERROR,
    "Batch terminated, 0 pages scanned.",
]
# The fake would hang for 30 s; a fail-fast scan must be over long before that.
FAST_S = 3.0
TIMEOUT_S = 4.0  # red: a scan that is not cut short gives up here, not after 30 s
GRACE_S = 0.3


class RecordingPopen:
    def __init__(self) -> None:
        self.procs: list[subprocess.Popen[bytes]] = []

    def __call__(self, argv: tuple[str, ...], **kwargs: Any) -> "subprocess.Popen[bytes]":
        proc = subprocess.Popen(argv, **kwargs)
        self.procs.append(proc)
        return proc


@pytest.fixture
def job(tmp_path: Path) -> ScanJob:
    return ScanJob(device=DEVICE, output_dir=tmp_path / "scans")


@pytest.fixture
def bin_dir(tmp_path: Path) -> Path:
    return install(tmp_path / "bin")


@pytest.fixture(autouse=True)
def short_graces(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run_module, "FAIL_FAST_GRACE_S", GRACE_S)
    monkeypatch.setattr(run_module, "TERMINATE_GRACE_S", GRACE_S)


def names(paths: tuple[Path, ...]) -> list[str]:
    return [p.name for p in paths]


# --- a real error stops the wait ---------------------------------------------------------------


def test_an_io_error_line_ends_the_scan_at_once_instead_of_waiting_for_scanimage(
    job: ScanJob, bin_dir: Path, tmp_path: Path
) -> None:
    marker = tmp_path / "sigterm-marker"
    env = fake_env(
        bin_dir, early_stderr_lines=SCANIMAGE_SAID[:3], hang=True, sigterm_marker=str(marker)
    )

    started = time.monotonic()
    with pytest.raises(ScanError) as excinfo:
        run_scan(job, env=env, timeout_s=TIMEOUT_S)

    assert time.monotonic() - started < FAST_S
    assert "Error during device I/O" in str(excinfo.value)
    assert excinfo.value.pages == ()
    assert marker.read_text() == "terminated"  # scanimage was asked to stop, not abandoned


def test_the_error_message_is_the_one_scanimage_gave_not_a_timeout(
    job: ScanJob, bin_dir: Path
) -> None:
    env = fake_env(bin_dir, early_stderr_lines=SCANIMAGE_SAID[:3], hang=True)

    with pytest.raises(ScanError) as excinfo:
        run_scan(job, env=env, timeout_s=TIMEOUT_S)

    assert "timed out" not in str(excinfo.value)
    assert "sane_start" in str(excinfo.value)


def test_scanimage_that_ignores_sigterm_is_killed_after_the_short_grace(
    job: ScanJob, bin_dir: Path
) -> None:
    popen = RecordingPopen()
    env = fake_env(bin_dir, early_stderr_lines=[IO_ERROR], hang=True, ignore_sigterm=True)

    started = time.monotonic()
    with pytest.raises(ScanError, match="Error during device I/O"):
        run_scan(job, env=env, popen=popen, timeout_s=TIMEOUT_S)

    assert time.monotonic() - started < FAST_S
    assert popen.procs[0].returncode == -signal.SIGKILL


def test_the_fail_fast_grace_is_short() -> None:
    assert 0 < run_module.FAIL_FAST_GRACE_S <= 2.0


@pytest.mark.parametrize(
    "line",
    [
        "scanimage: sane_start: Document feeder jammed",
        "scanimage: sane_start: Scanner cover is open",
        "scanimage: sane_start: Invalid argument",
        "scanimage: sane_start: Device busy",
        "scanimage: sane_read: Error during device I/O",
        "scanimage: sane_read: Out of memory",
    ],
)
def test_every_real_error_status_stops_the_scan(job: ScanJob, bin_dir: Path, line: str) -> None:
    env = fake_env(bin_dir, early_stderr_lines=[line], hang=True)

    started = time.monotonic()
    with pytest.raises(ScanError) as excinfo:
        run_scan(job, env=env, timeout_s=TIMEOUT_S)

    assert time.monotonic() - started < FAST_S
    assert line.split(": ", 2)[2] in str(excinfo.value)


def test_a_page_error_after_good_pages_keeps_those_pages(job: ScanJob, bin_dir: Path) -> None:
    env = fake_env(
        bin_dir,
        pages=2,
        early_stderr_lines=["scanimage: sane_start: Document feeder jammed"],
        hang=True,
    )

    started = time.monotonic()
    with pytest.raises(ScanError, match="jammed") as excinfo:
        run_scan(job, env=env, timeout_s=TIMEOUT_S)

    assert time.monotonic() - started < FAST_S
    assert names(excinfo.value.pages) == ["page-0001.png", "page-0002.png"]


def test_pages_finished_before_the_error_are_announced(job: ScanJob, bin_dir: Path) -> None:
    announced: list[int] = []
    env = fake_env(bin_dir, pages=2, early_stderr_lines=[IO_ERROR], hang=True)

    started = time.monotonic()
    with pytest.raises(ScanError):
        run_scan(job, env=env, timeout_s=TIMEOUT_S, on_progress=announced.append)

    assert time.monotonic() - started < FAST_S
    assert announced == [1, 2]


# --- what is not an error ----------------------------------------------------------------------


def test_the_normal_end_of_the_batch_is_waited_for_and_is_a_success(
    job: ScanJob, bin_dir: Path, tmp_path: Path
) -> None:
    marker = tmp_path / "sigterm-marker"
    env = fake_env(
        bin_dir,
        pages=2,
        early_stderr_lines=[OUT_OF_DOCS],
        exit_delay_s=GRACE_S * 3,  # scanimage's slow exit path: it must not be cut short
        exit_code=7,
        sigterm_marker=str(marker),
    )

    result = run_scan(job, env=env, timeout_s=TIMEOUT_S)

    assert names(result.pages) == ["page-0001.png", "page-0002.png"]
    assert not marker.exists()


def test_a_line_that_scanimage_did_not_print_is_not_a_failure(
    job: ScanJob, bin_dir: Path, tmp_path: Path
) -> None:
    """The old behaviour stays for output that is not scanimage's own status line."""
    marker = tmp_path / "sigterm-marker"
    env = fake_env(
        bin_dir,
        pages=1,
        early_stderr_lines=["sane_start: Document feeder jammed"],
        exit_delay_s=GRACE_S * 3,
        exit_code=6,
        sigterm_marker=str(marker),
    )

    with pytest.raises(ScanError, match="exit status 6"):
        run_scan(job, env=env, timeout_s=TIMEOUT_S)

    assert not marker.exists()


def test_a_status_text_that_is_not_known_degrades_to_waiting_for_the_exit(
    job: ScanJob, bin_dir: Path, tmp_path: Path
) -> None:
    """A localised "out of documents" must not turn a finished batch into an error."""
    marker = tmp_path / "sigterm-marker"
    env = fake_env(
        bin_dir,
        pages=2,
        early_stderr_lines=["scanimage: sane_start: Zufuhr leer"],
        exit_delay_s=GRACE_S * 3,
        exit_code=7,
        sigterm_marker=str(marker),
    )

    result = run_scan(job, env=env, timeout_s=TIMEOUT_S)

    assert len(result.pages) == 2
    assert not marker.exists()


def test_a_scanimage_that_exits_at_once_after_its_error_still_reports_it(
    job: ScanJob, bin_dir: Path
) -> None:
    """Whether the exit or the error line is noticed first is a race; either way it is reported."""
    env = fake_env(bin_dir, early_stderr_lines=SCANIMAGE_SAID[2:], exit_code=9)

    with pytest.raises(ScanError, match="Error during device I/O") as excinfo:
        run_scan(job, env=env, timeout_s=TIMEOUT_S)

    assert excinfo.value.returncode in (None, 9)


# --- the stderr monitor ------------------------------------------------------------------------


@pytest.fixture
def monitor(job: ScanJob) -> Iterator[StderrMonitor]:
    read_fd, write_fd = os.pipe()
    try:
        with StderrMonitor(job, None, read_fd) as monitor:
            yield monitor
    finally:
        os.close(read_fd)
        os.close(write_fd)


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (IO_ERROR, "Error during device I/O"),
        ("scanimage: sane_read: Document feeder jammed", "Document feeder jammed"),
        (OUT_OF_DOCS, None),
        ("scanimage: sane_start: Operation was cancelled", None),
        ("scanimage: sane_read: End of file reached", None),
        ("scanimage: sane_start: Zufuhr leer", None),
        ("sane_start: Error during device I/O", None),
        ("scanimage: Scanned page 1. (scanner status = 0)", None),
    ],
)
def test_the_monitor_recognises_only_real_scanimage_errors(
    monitor: StderrMonitor, line: str, expected: str | None
) -> None:
    monitor.feed(f"{line}\n".encode())

    if expected is None:
        assert monitor.failure is None
    else:
        assert monitor.failure is not None
        assert expected in monitor.failure


def test_the_first_error_is_the_one_kept(monitor: StderrMonitor) -> None:
    monitor.feed(b"scanimage: sane_start: Document feeder jammed\n")
    monitor.feed(b"scanimage: sane_start: Error during device I/O\n")

    assert monitor.failure is not None
    assert "jammed" in monitor.failure
