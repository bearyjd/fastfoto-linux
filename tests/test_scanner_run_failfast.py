"""run_scan stops at once when scanimage reports a real error, and not at the normal batch end."""

import os
import signal
import subprocess
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from fastfoto_linux.scanner import run as run_module
from fastfoto_linux.scanner import unclean
from fastfoto_linux.scanner.errors import NoDocumentsError, ScanCancelledError, ScanError
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
GRACE_S = 0.3  # the fail-fast grace while these tests run
CANCEL_GRACE_S = 2.0  # the grace of a user Cancel while these tests run
# What the runner really uses, read when this module is imported, before the fixture below
# shortens them: a test that reads them later would only ever see the shortened values.
DEFAULT_TERMINATE_GRACE_S = run_module.TERMINATE_GRACE_S
DEFAULT_FAIL_FAST_GRACE_S = run_module.FAIL_FAST_GRACE_S


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
    monkeypatch.setattr(run_module, "TERMINATE_GRACE_S", CANCEL_GRACE_S)


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

    assert time.monotonic() - started < CANCEL_GRACE_S - 0.3  # the short grace, not the long one
    assert popen.procs[0].returncode == -signal.SIGKILL


def test_the_default_fail_fast_grace_is_short() -> None:
    assert 0 < DEFAULT_FAIL_FAST_GRACE_S <= 2.0


def test_the_default_grace_of_a_user_cancel_is_10_seconds() -> None:
    """A mid-page sane_cancel needs time; nothing shows that 5 s is enough."""
    assert DEFAULT_TERMINATE_GRACE_S == 10.0


def test_a_user_cancel_gives_scanimage_the_long_grace_before_it_is_killed(
    job: ScanJob, bin_dir: Path
) -> None:
    popen = RecordingPopen()
    cancel = threading.Event()
    asked: list[float] = []

    def cancel_after_the_first_page(page: int) -> None:
        asked.append(time.monotonic())
        cancel.set()

    env = fake_env(bin_dir, pages=1, hang=True, ignore_sigterm=True)

    with pytest.raises(ScanCancelledError):
        run_scan(
            job,
            env=env,
            popen=popen,
            timeout_s=TIMEOUT_S * 2,
            on_progress=cancel_after_the_first_page,
            cancel=cancel,
        )

    waited = time.monotonic() - asked[0]
    assert CANCEL_GRACE_S - 0.3 <= waited < CANCEL_GRACE_S + 1.5
    assert popen.procs[0].returncode == -signal.SIGKILL


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


# --- the note that this scan ended abnormally (the evidence for freeing the scanner later) -----


def noted() -> bool:
    return unclean.is_marked(1, 2)  # DEVICE is epsonds:libusb:001:002


def test_a_fail_fast_error_leaves_the_note(job: ScanJob, bin_dir: Path) -> None:
    env = fake_env(bin_dir, early_stderr_lines=SCANIMAGE_SAID[:3], hang=True)

    with pytest.raises(ScanError):
        run_scan(job, env=env, timeout_s=TIMEOUT_S)

    assert noted()


def test_a_scanimage_that_exits_with_an_error_status_at_once_leaves_the_note(
    job: ScanJob, bin_dir: Path
) -> None:
    env = fake_env(bin_dir, early_stderr_lines=SCANIMAGE_SAID[2:], exit_code=9)

    with pytest.raises(ScanError):
        run_scan(job, env=env, timeout_s=TIMEOUT_S)

    assert noted()


def test_a_scanimage_that_has_to_be_killed_leaves_the_note(job: ScanJob, bin_dir: Path) -> None:
    cancel = threading.Event()
    env = fake_env(bin_dir, pages=1, hang=True, ignore_sigterm=True)

    with pytest.raises(ScanCancelledError):
        run_scan(
            job,
            env=env,
            timeout_s=TIMEOUT_S * 2,
            on_progress=lambda page: cancel.set(),
            cancel=cancel,
        )

    assert noted()


def test_a_cancel_that_scanimage_honours_leaves_no_note(job: ScanJob, bin_dir: Path) -> None:
    cancel = threading.Event()
    env = fake_env(bin_dir, pages=1, hang=True)  # SIGTERM ends it, as sane_cancel would

    with pytest.raises(ScanCancelledError):
        run_scan(
            job, env=env, timeout_s=TIMEOUT_S, on_progress=lambda page: cancel.set(), cancel=cancel
        )

    assert not unclean.marker_path().exists()


def test_the_normal_end_of_a_batch_leaves_no_note(job: ScanJob, bin_dir: Path) -> None:
    env = fake_env(bin_dir, pages=2, early_stderr_lines=[OUT_OF_DOCS], exit_code=7)

    run_scan(job, env=env, timeout_s=TIMEOUT_S)

    assert not unclean.marker_path().exists()


def test_an_empty_feeder_leaves_no_note(job: ScanJob, bin_dir: Path) -> None:
    env = fake_env(bin_dir, early_stderr_lines=[OUT_OF_DOCS], exit_code=7)

    with pytest.raises(NoDocumentsError):
        run_scan(job, env=env, timeout_s=TIMEOUT_S)

    assert not unclean.marker_path().exists()


def test_a_scan_that_succeeds_clears_nothing_and_notes_nothing(job: ScanJob, bin_dir: Path) -> None:
    env = fake_env(bin_dir, pages=1, exit_code=0)

    run_scan(job, env=env, timeout_s=TIMEOUT_S)

    assert not unclean.marker_path().exists()


def test_a_status_reply_exit_after_pages_leaves_no_note(job: ScanJob, bin_dir: Path) -> None:
    """Exit 6 (jammed) is a reply: the command channel was in step (round 2 changed this)."""
    env = fake_env(bin_dir, pages=1, exit_code=6)

    with pytest.raises(ScanError, match="exit status 6"):
        run_scan(job, env=env, timeout_s=TIMEOUT_S)

    assert not unclean.marker_path().exists()


def test_a_network_scanner_leaves_no_note(tmp_path: Path, bin_dir: Path) -> None:
    net_job = ScanJob(device="epsonds:net:203.0.113.7", output_dir=tmp_path / "net-scans")
    env = fake_env(bin_dir, early_stderr_lines=[IO_ERROR], hang=True)

    with pytest.raises(ScanError):
        run_scan(net_job, env=env, timeout_s=TIMEOUT_S)

    assert not unclean.marker_path().exists()


def test_a_note_that_cannot_be_written_does_not_replace_the_scan_error(
    job: ScanJob, bin_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blocker = tmp_path / "a-file"
    blocker.write_text("not a folder")
    monkeypatch.setenv("XDG_STATE_HOME", str(blocker / "state"))
    env = fake_env(bin_dir, pages=1, early_stderr_lines=[IO_ERROR], hang=True)

    with pytest.raises(ScanError, match="Error during device I/O") as excinfo:
        run_scan(job, env=env, timeout_s=TIMEOUT_S)

    assert names(excinfo.value.pages) == ["page-0001.png"]
