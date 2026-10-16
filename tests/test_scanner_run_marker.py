"""Which scan endings leave the note "this scan ended abnormally" (review round 2, item 1).

The note is the evidence that lets the next pre-scan check send filler to a silent scanner, so it
must only be written when our own command channel may have been left half-way through a command: an
I/O error, a SIGKILL after the grace, or a scanimage that died of a signal. A status reply (busy,
jammed, cover open, access denied...) proves the channel was in step; writing the note for it would
let the next check pad a scanner that is only busy with another device.
"""

import os
import signal
import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from fastfoto_linux.scanner import run as run_module
from fastfoto_linux.scanner import unclean
from fastfoto_linux.scanner.errors import ScanError
from fastfoto_linux.scanner.job import ScanJob
from fastfoto_linux.scanner.run import run_scan
from fastfoto_linux.scanner.stderr_monitor import StderrMonitor
from tests._fake_scanimage import fake_env, install

DEVICE = "epsonds:libusb:001:002"
IO_ERROR = "scanimage: sane_start: Error during device I/O"
TIMEOUT_S = 4.0
GRACE_S = 0.3
# What a status reply looks like: (SANE's text, the exit status scanimage ends with).
STATUS_REPLIES = [
    ("Device busy", 3),
    ("Document feeder jammed", 6),
    ("Scanner cover is open", 8),
    ("Access to resource has been denied", 11),
    ("Operation not supported", 1),
    ("Invalid argument", 4),
    ("Out of memory", 10),
]
REPLY_IDS = ["busy", "jammed", "cover-open", "access-denied", "unsupported", "invalid", "no-memory"]
OTHER_EXIT_STATUSES = [1, 2, 3, 4, 6, 8, 10, 11]


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


@pytest.fixture
def monitor(job: ScanJob) -> Iterator[StderrMonitor]:
    read_fd, write_fd = os.pipe()  # the monitor is fed by hand: nothing is read from the pipe
    try:
        with StderrMonitor(job, None, read_fd) as monitor:
            yield monitor
    finally:
        os.close(read_fd)
        os.close(write_fd)


def scan_fails(job: ScanJob, bin_dir: Path, **spec: object) -> None:
    with pytest.raises(ScanError):
        run_scan(job, env=fake_env(bin_dir, **spec), timeout_s=TIMEOUT_S)


def noted() -> bool:
    return unclean.is_marked(1, 2)  # DEVICE is epsonds:libusb:001:002


# --- a status reply is no evidence -------------------------------------------------------------


@pytest.mark.parametrize(("text", "status"), STATUS_REPLIES, ids=REPLY_IDS)
def test_a_status_reply_that_scanimage_is_stopped_after_leaves_no_note(
    job: ScanJob, bin_dir: Path, text: str, status: int
) -> None:
    scan_fails(job, bin_dir, early_stderr_lines=[f"scanimage: sane_start: {text}"], hang=True)

    assert not unclean.marker_path().exists()


@pytest.mark.parametrize(("text", "status"), STATUS_REPLIES, ids=REPLY_IDS)
def test_a_status_reply_with_the_exit_status_of_scanimage_leaves_no_note(
    job: ScanJob, bin_dir: Path, text: str, status: int
) -> None:
    lines = [f"scanimage: sane_start: {text}"]
    scan_fails(job, bin_dir, early_stderr_lines=lines, exit_code=status)

    assert not unclean.marker_path().exists()


@pytest.mark.parametrize("status", OTHER_EXIT_STATUSES)
def test_an_error_exit_status_that_is_not_an_io_error_leaves_no_note(
    job: ScanJob, bin_dir: Path, status: int
) -> None:
    scan_fails(job, bin_dir, pages=1, exit_code=status)

    assert not unclean.marker_path().exists()


def test_a_scan_that_runs_out_of_time_and_obeys_sigterm_leaves_no_note(
    job: ScanJob, bin_dir: Path
) -> None:
    with pytest.raises(ScanError, match="timed out"):
        run_scan(job, env=fake_env(bin_dir, hang=True), timeout_s=0.5)

    assert not unclean.marker_path().exists()


# --- what is evidence --------------------------------------------------------------------------


def test_an_io_error_line_leaves_the_note_whatever_the_exit_status(
    job: ScanJob, bin_dir: Path
) -> None:
    scan_fails(job, bin_dir, early_stderr_lines=[IO_ERROR], exit_code=3)

    assert noted()


def test_an_io_error_line_that_follows_another_error_still_leaves_the_note(
    job: ScanJob, bin_dir: Path
) -> None:
    lines = ["scanimage: sane_start: Document feeder jammed", IO_ERROR]
    scan_fails(job, bin_dir, early_stderr_lines=lines, hang=True)

    assert noted()


def test_an_io_error_while_reading_a_page_leaves_the_note(job: ScanJob, bin_dir: Path) -> None:
    lines = ["scanimage: sane_read: Error during device I/O"]
    scan_fails(job, bin_dir, pages=1, early_stderr_lines=lines, hang=True)

    assert noted()


def test_exit_status_9_alone_leaves_the_note(job: ScanJob, bin_dir: Path) -> None:
    scan_fails(job, bin_dir, pages=1, exit_code=9)  # SANE_STATUS_IO_ERROR, no text

    assert noted()


def test_a_scanimage_that_died_of_a_signal_leaves_the_note(job: ScanJob, bin_dir: Path) -> None:
    scan_fails(job, bin_dir, pages=1, die_by_signal=int(signal.SIGUSR1))

    assert noted()


def test_a_status_reply_followed_by_a_sigkill_after_the_grace_leaves_the_note(
    job: ScanJob, bin_dir: Path
) -> None:
    lines = ["scanimage: sane_start: Device busy"]
    scan_fails(job, bin_dir, early_stderr_lines=lines, hang=True, ignore_sigterm=True)

    assert noted()


# --- an interrupt or a failing callback: scanimage is stopped, and a kill is noted -------------


def fail_the_callback(page: int) -> None:
    raise RuntimeError("callback failed")


def test_a_failing_callback_that_scanimage_ignores_sigterm_for_leaves_the_note(
    job: ScanJob, bin_dir: Path
) -> None:
    env = fake_env(bin_dir, pages=1, hang=True, ignore_sigterm=True)

    with pytest.raises(RuntimeError, match="callback failed"):
        run_scan(job, env=env, timeout_s=TIMEOUT_S, on_progress=fail_the_callback)

    assert noted()  # scanimage had to be killed: a command may have been cut short


def test_a_ctrl_c_that_scanimage_ignores_sigterm_for_leaves_the_note(
    job: ScanJob, bin_dir: Path
) -> None:
    env = fake_env(bin_dir, pages=1, hang=True, ignore_sigterm=True)
    interrupt = threading.Timer(0.3, os.kill, (os.getpid(), signal.SIGINT))

    def interrupt_soon(page: int) -> None:
        interrupt.start()  # scanimage is now idle in its hang; Ctrl-C reaches us shortly

    try:
        with pytest.raises(KeyboardInterrupt):
            run_scan(job, env=env, timeout_s=TIMEOUT_S, on_progress=interrupt_soon)
    finally:
        interrupt.cancel()

    assert noted()


def test_an_interrupt_before_the_supervision_starts_leaves_the_note_for_a_kill(
    job: ScanJob, bin_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def started(argv: tuple[str, ...], **options: object) -> "subprocess.Popen[bytes]":
        proc = subprocess.Popen(argv, **options)  # type: ignore[call-overload]
        assert proc.stderr is not None
        for _ in range(2):  # "Scanning page 1", "Scanned page 1": the fake now only hangs,
            proc.stderr.readline()  # ignoring SIGTERM as asked, and writes nothing more
        return proc

    def interrupted(*args: object) -> object:
        raise KeyboardInterrupt  # Ctrl-C lands after scanimage started, before it is watched

    monkeypatch.setattr(run_module, "StderrMonitor", interrupted)
    env = fake_env(bin_dir, pages=1, hang=True, ignore_sigterm=True)

    with pytest.raises(KeyboardInterrupt):
        run_scan(job, env=env, timeout_s=TIMEOUT_S, popen=started)

    assert noted()


def test_a_failing_callback_that_scanimage_obeys_leaves_no_note(
    job: ScanJob, bin_dir: Path
) -> None:
    env = fake_env(bin_dir, pages=1, hang=True)

    with pytest.raises(RuntimeError, match="callback failed"):
        run_scan(job, env=env, timeout_s=TIMEOUT_S, on_progress=fail_the_callback)

    assert not unclean.marker_path().exists()  # a clean SIGTERM stop proves the channel in step


# --- the monitor tells an I/O error from the other errors --------------------------------------


@pytest.mark.parametrize(
    ("lines", "expected"),
    [
        ([IO_ERROR], True),
        (["scanimage: sane_read: Error during device I/O"], True),
        (["scanimage: sane_start: Device busy", IO_ERROR], True),
        (["scanimage: sane_start: Device busy"], False),
        (["scanimage: sane_start: Document feeder jammed"], False),
        (["scanimage: sane_start: Operation was cancelled"], False),
        (["sane_start: Error during device I/O"], False),
        (["Scanned page 1. (scanner status = 0)"], False),
    ],
    ids=["start", "read", "after-busy", "busy", "jammed", "cancelled", "not-scanimage", "page"],
)
def test_the_monitor_remembers_an_io_error_even_after_another_error(
    monitor: StderrMonitor, lines: list[str], expected: bool
) -> None:
    for line in lines:
        monitor.feed(f"{line}\n".encode())

    assert monitor.io_error is expected
