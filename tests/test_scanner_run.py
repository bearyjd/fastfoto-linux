"""run_scan against a fake ``scanimage`` executable (a real subprocess; see _fake_scanimage)."""

import json
import os
import signal
import subprocess
import threading
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest

from fastfoto_linux.scanner import run as run_module
from fastfoto_linux.scanner.errors import (
    NoDocumentsError,
    OutputDirError,
    OutputNotEmptyError,
    ScanCancelledError,
    ScanError,
    ScannerError,
)
from fastfoto_linux.scanner.job import ScanJob, build_argv
from fastfoto_linux.scanner.run import ScanResult, run_scan
from tests._fake_scanimage import fake_env, install

DEVICE = "epsonds:libusb:001:002"
SANE_STATUS_NO_DOCS = 7
SANE_STATUS_JAMMED = 6
SANE_STATUS_IO_ERROR = 9
OUT_OF_DOCS = "scanimage: sane_start: Document feeder out of documents"
IS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0


class RecordingPopen:
    """subprocess.Popen that remembers how it was called and which processes it started."""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], dict[str, Any]]] = []
        self.procs: list[subprocess.Popen[bytes]] = []

    def __call__(self, argv: tuple[str, ...], **kwargs: Any) -> "subprocess.Popen[bytes]":
        self.calls.append((argv, kwargs))
        proc = subprocess.Popen(argv, **kwargs)
        self.procs.append(proc)
        return proc


def never_started(*args: Any, **kwargs: Any) -> "subprocess.Popen[bytes]":
    raise AssertionError("scanimage must not be started")


@pytest.fixture
def job(tmp_path: Path) -> ScanJob:
    return ScanJob(device=DEVICE, output_dir=tmp_path / "scans")


@pytest.fixture
def bin_dir(tmp_path: Path) -> Path:
    return install(tmp_path / "bin")


def names(paths: tuple[Path, ...]) -> list[str]:
    return [p.name for p in paths]


# --- success -------------------------------------------------------------------------------


def test_success_returns_the_pages_in_order(job: ScanJob, bin_dir: Path) -> None:
    result = run_scan(job, env=fake_env(bin_dir, pages=3, stderr_lines=[OUT_OF_DOCS]))

    assert names(result.pages) == ["page-0001.png", "page-0002.png", "page-0003.png"]
    assert all(page.parent == job.output_dir for page in result.pages)
    assert not hasattr(result, "returncode")


def test_pages_are_sorted_by_number_not_by_text(job: ScanJob, bin_dir: Path) -> None:
    result = run_scan(job, env=fake_env(bin_dir, numbers=[10000, 2, 9999, 1]))

    assert names(result.pages) == [
        "page-0001.png",
        "page-0002.png",
        "page-9999.png",
        "page-10000.png",
    ]


def test_only_pages_with_the_jobs_prefix_and_numbering_are_collected(
    tmp_path: Path, bin_dir: Path
) -> None:
    job = ScanJob(device=DEVICE, output_dir=tmp_path / "scans", file_prefix="batch")
    job.output_dir.mkdir()
    others = ["page-0001.png", "batch-1.png", "batch-0001.png.part", "batch-0001.jpg", "x.txt"]
    for name in others:
        (job.output_dir / name).write_bytes(b"other")

    result = run_scan(job, env=fake_env(bin_dir, pages=1))

    assert names(result.pages) == ["batch-0001.png"]


def test_page_numbers_written_with_non_ascii_digits_are_not_pages(
    job: ScanJob, bin_dir: Path
) -> None:
    job.output_dir.mkdir()
    (job.output_dir / "page-١٢٣٤.png").write_bytes(b"other")  # Arabic-Indic

    result = run_scan(job, env=fake_env(bin_dir, pages=1))

    assert names(result.pages) == ["page-0001.png"]


def test_output_dir_is_created_when_missing(tmp_path: Path, bin_dir: Path) -> None:
    job = ScanJob(device=DEVICE, output_dir=tmp_path / "a" / "b" / "scans")

    result = run_scan(job, env=fake_env(bin_dir, pages=1))

    assert job.output_dir.is_dir()
    assert len(result.pages) == 1


def test_percent_sign_in_output_dir_round_trips_through_the_batch_pattern(
    tmp_path: Path, bin_dir: Path
) -> None:
    job = ScanJob(device=DEVICE, output_dir=tmp_path / "100%done")

    result = run_scan(job, env=fake_env(bin_dir, pages=2))

    assert names(result.pages) == ["page-0001.png", "page-0002.png"]
    assert all(page.parent == job.output_dir for page in result.pages)


def test_popen_gets_an_argv_tuple_the_env_and_safe_stream_options(
    job: ScanJob, bin_dir: Path
) -> None:
    popen = RecordingPopen()
    env = fake_env(bin_dir, pages=1)

    run_scan(job, env=env, popen=popen)

    ((argv, kwargs),) = popen.calls
    assert argv == build_argv(job)
    assert isinstance(argv, tuple)
    assert kwargs["env"] == env
    assert kwargs["stdin"] == subprocess.DEVNULL
    assert kwargs["stdout"] == subprocess.DEVNULL
    assert kwargs["stderr"] == subprocess.PIPE
    assert not kwargs.get("shell", False)


def test_scanimage_sees_the_argv_the_env_and_a_closed_stdin(
    job: ScanJob, bin_dir: Path, tmp_path: Path
) -> None:
    record = tmp_path / "record.json"
    env = {**fake_env(bin_dir, pages=1, record_to=str(record)), "FAKE_PROBE": "hello"}

    run_scan(job, env=env)

    seen = json.loads(record.read_text())
    assert tuple(seen["argv"]) == build_argv(job)[1:]
    assert seen["probe"] == "hello"
    assert seen["stdin_eof"] is True


def test_scanimage_executable_can_be_chosen(job: ScanJob, tmp_path: Path) -> None:
    custom_bin = install(tmp_path / "custom-bin", name="my-scanimage")
    popen = RecordingPopen()

    run_scan(job, env=fake_env(custom_bin, pages=1), popen=popen, scanimage="my-scanimage")

    assert popen.calls[0][0][0] == "my-scanimage"


def test_env_mapping_is_not_mutated(job: ScanJob, bin_dir: Path) -> None:
    env = fake_env(bin_dir, pages=1)
    before = dict(env)

    run_scan(job, env=env)

    assert env == before


def test_timeout_none_means_no_timeout(job: ScanJob, bin_dir: Path) -> None:
    result = run_scan(job, env=fake_env(bin_dir, pages=1), timeout_s=None)

    assert len(result.pages) == 1


def test_scan_result_is_frozen() -> None:
    result = ScanResult(pages=())

    with pytest.raises(FrozenInstanceError):
        result.pages = ()  # type: ignore[misc]


# --- output directory problems -------------------------------------------------------------


def test_existing_pages_are_refused_and_scanimage_is_never_started(job: ScanJob) -> None:
    job.output_dir.mkdir()
    (job.output_dir / "page-0001.png").write_bytes(b"old")

    with pytest.raises(OutputNotEmptyError, match="page-") as excinfo:
        run_scan(job, env={}, popen=never_started)

    assert isinstance(excinfo.value, FileExistsError)
    assert isinstance(excinfo.value, ScannerError)
    assert (job.output_dir / "page-0001.png").read_bytes() == b"old"


def assert_output_dir_error(job: ScanJob) -> None:
    with pytest.raises(OutputDirError) as excinfo:
        run_scan(job, env={}, popen=never_started)
    assert isinstance(excinfo.value, OSError)
    assert isinstance(excinfo.value, ScannerError)
    assert str(job.output_dir) in str(excinfo.value)


def test_output_dir_that_is_a_file_is_an_output_dir_error(job: ScanJob) -> None:
    job.output_dir.write_bytes(b"not a directory")

    assert_output_dir_error(job)


def test_output_dir_below_a_file_is_an_output_dir_error(tmp_path: Path) -> None:
    (tmp_path / "file").write_bytes(b"")

    assert_output_dir_error(ScanJob(device=DEVICE, output_dir=tmp_path / "file" / "scans"))


def test_dangling_symlink_as_output_dir_is_an_output_dir_error(
    job: ScanJob, tmp_path: Path
) -> None:
    job.output_dir.symlink_to(tmp_path / "nowhere")

    assert_output_dir_error(job)


@pytest.mark.skipif(IS_ROOT, reason="root ignores directory permissions")
def test_read_only_output_dir_is_an_output_dir_error(job: ScanJob) -> None:
    job.output_dir.mkdir()
    job.output_dir.chmod(0o500)
    try:
        assert_output_dir_error(job)
    finally:
        job.output_dir.chmod(0o700)


@pytest.mark.skipif(IS_ROOT, reason="root ignores directory permissions")
def test_unlistable_output_dir_is_an_output_dir_error(job: ScanJob) -> None:
    job.output_dir.mkdir()
    job.output_dir.chmod(0o300)
    try:
        assert_output_dir_error(job)
    finally:
        job.output_dir.chmod(0o700)


# --- end of stack and failures -------------------------------------------------------------


def test_exit_status_7_without_pages_means_the_feeder_was_empty(
    job: ScanJob, bin_dir: Path
) -> None:
    env = fake_env(bin_dir, exit_code=SANE_STATUS_NO_DOCS, stderr_lines=["Zufuhr leer"])

    with pytest.raises(NoDocumentsError):
        run_scan(job, env=env)


def test_exit_status_7_after_some_pages_is_a_normal_end_of_the_stack(
    job: ScanJob, bin_dir: Path
) -> None:
    result = run_scan(job, env=fake_env(bin_dir, pages=2, exit_code=SANE_STATUS_NO_DOCS))

    assert len(result.pages) == 2


def test_out_of_documents_text_alone_does_not_make_an_error_a_no_documents_error(
    job: ScanJob, bin_dir: Path
) -> None:
    env = fake_env(bin_dir, exit_code=1, stderr_lines=[OUT_OF_DOCS])

    with pytest.raises(ScanError, match="exit status 1"):
        run_scan(job, env=env)


def test_an_io_error_is_not_hidden_by_out_of_documents_text(job: ScanJob, bin_dir: Path) -> None:
    env = fake_env(bin_dir, exit_code=SANE_STATUS_IO_ERROR, stderr_lines=[OUT_OF_DOCS])

    with pytest.raises(ScanError, match="exit status 9"):
        run_scan(job, env=env)


def test_failure_without_pages_reports_the_exit_status_and_last_five_stderr_lines(
    job: ScanJob, bin_dir: Path
) -> None:
    lines = [f"line {i}" for i in range(1, 8)] + ["", "   "]
    env = fake_env(bin_dir, exit_code=SANE_STATUS_IO_ERROR, stderr_lines=lines)

    with pytest.raises(ScanError) as excinfo:
        run_scan(job, env=env)

    message = str(excinfo.value)
    assert all(f"line {i}" in message for i in range(3, 8))
    assert "line 1" not in message
    assert "line 2" not in message
    assert "exit status 9" in message
    assert excinfo.value.returncode == SANE_STATUS_IO_ERROR
    assert excinfo.value.pages == ()


def test_failure_after_some_pages_keeps_the_finished_pages_on_the_error(
    job: ScanJob, bin_dir: Path
) -> None:
    env = fake_env(
        bin_dir,
        pages=2,
        exit_code=SANE_STATUS_JAMMED,
        stderr_lines=["sane_start: Document feeder jammed"],
    )

    with pytest.raises(ScanError, match="jammed") as excinfo:
        run_scan(job, env=env)

    assert names(excinfo.value.pages) == ["page-0001.png", "page-0002.png"]
    assert excinfo.value.returncode == SANE_STATUS_JAMMED


def test_exit_zero_without_any_page_is_an_error_not_a_silent_success(
    job: ScanJob, bin_dir: Path
) -> None:
    with pytest.raises(ScanError, match="no pages"):
        run_scan(job, env=fake_env(bin_dir))


def test_stderr_that_is_not_utf8_is_decoded_with_replacement_characters(
    job: ScanJob, bin_dir: Path
) -> None:
    env = fake_env(bin_dir, exit_code=SANE_STATUS_IO_ERROR, stderr_hex=b"bad \xff byte\n".hex())

    with pytest.raises(ScanError) as excinfo:
        run_scan(job, env=env)

    assert "bad � byte" in str(excinfo.value)


def test_a_last_stderr_line_without_a_newline_is_kept(job: ScanJob, bin_dir: Path) -> None:
    env = fake_env(bin_dir, exit_code=SANE_STATUS_IO_ERROR, stderr_hex=b"no newline".hex())

    with pytest.raises(ScanError, match="no newline"):
        run_scan(job, env=env)


def test_failure_without_any_stderr_output_still_has_a_message(job: ScanJob, bin_dir: Path) -> None:
    with pytest.raises(ScanError, match="no error output"):
        run_scan(job, env=fake_env(bin_dir, exit_code=SANE_STATUS_IO_ERROR))


def test_scanimage_that_cannot_be_started_raises_scan_error(job: ScanJob, tmp_path: Path) -> None:
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()

    with pytest.raises(ScanError, match="could not start scanimage") as excinfo:
        run_scan(job, env=fake_env(empty_bin))

    assert isinstance(excinfo.value.__cause__, FileNotFoundError)


# --- progress ------------------------------------------------------------------------------


def test_progress_is_reported_per_page_once_the_page_file_exists(
    job: ScanJob, bin_dir: Path
) -> None:
    seen: list[tuple[int, bool]] = []

    def on_progress(page: int) -> None:
        seen.append((page, (job.output_dir / f"page-{page:04d}.png").is_file()))

    run_scan(job, env=fake_env(bin_dir, pages=3, rename_delay_s=0.15), on_progress=on_progress)

    assert seen == [(1, True), (2, True), (3, True)]


def test_progress_lines_split_across_reads_are_still_recognised(
    job: ScanJob, bin_dir: Path
) -> None:
    seen: list[int] = []

    run_scan(job, env=fake_env(bin_dir, pages=2, split_lines=True), on_progress=seen.append)

    assert seen == [1, 2]


def test_a_page_that_scanimage_reports_as_failed_is_not_announced(
    job: ScanJob, bin_dir: Path
) -> None:
    seen: list[int] = []
    env = fake_env(bin_dir, pages=2, fail_last_page_status=SANE_STATUS_IO_ERROR, exit_code=9)

    with pytest.raises(ScanError) as excinfo:
        run_scan(job, env=env, on_progress=seen.append)

    assert seen == [1]
    assert names(excinfo.value.pages) == ["page-0001.png"]


def test_a_failing_progress_callback_stops_scanimage_gracefully_and_propagates(
    job: ScanJob, bin_dir: Path, tmp_path: Path
) -> None:
    marker = tmp_path / "sigterm-marker"
    env = fake_env(bin_dir, pages=1, hang=True, sigterm_marker=str(marker))

    def on_progress(page: int) -> None:
        raise RuntimeError("callback failed")

    with pytest.raises(RuntimeError, match="callback failed"):
        run_scan(job, env=env, on_progress=on_progress)

    assert marker.read_text() == "terminated"


# --- cancel --------------------------------------------------------------------------------


def test_cancel_terminates_scanimage_gracefully_and_keeps_the_finished_pages(
    job: ScanJob, bin_dir: Path, tmp_path: Path
) -> None:
    marker = tmp_path / "sigterm-marker"
    cancel = threading.Event()
    env = fake_env(bin_dir, pages=1, hang=True, sigterm_marker=str(marker))

    with pytest.raises(ScanCancelledError) as excinfo:
        run_scan(job, env=env, on_progress=lambda page: cancel.set(), cancel=cancel)

    assert isinstance(excinfo.value, ScannerError)
    assert names(excinfo.value.pages) == ["page-0001.png"]
    assert marker.read_text() == "terminated"


def test_cancel_set_before_the_start_never_starts_scanimage(job: ScanJob) -> None:
    cancel = threading.Event()
    cancel.set()

    with pytest.raises(ScanCancelledError) as excinfo:
        run_scan(job, env={}, popen=never_started, cancel=cancel)

    assert excinfo.value.pages == ()


def test_unset_cancel_event_does_not_disturb_a_scan(job: ScanJob, bin_dir: Path) -> None:
    result = run_scan(job, env=fake_env(bin_dir, pages=2), cancel=threading.Event())

    assert len(result.pages) == 2


# --- timeout -------------------------------------------------------------------------------


def test_timeout_terminates_gracefully_and_raises_scan_error_with_the_pages_so_far(
    job: ScanJob, bin_dir: Path, tmp_path: Path
) -> None:
    marker = tmp_path / "sigterm-marker"
    env = fake_env(bin_dir, pages=1, hang=True, sigterm_marker=str(marker))

    with pytest.raises(ScanError, match="timed out") as excinfo:
        run_scan(job, env=env, timeout_s=1.0)

    assert names(excinfo.value.pages) == ["page-0001.png"]
    assert excinfo.value.returncode is None
    assert marker.read_text() == "terminated"


def test_scanimage_that_ignores_sigterm_is_killed_after_the_grace_period(
    job: ScanJob, bin_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run_module, "TERMINATE_GRACE_S", 0.3)
    popen = RecordingPopen()

    with pytest.raises(ScanError, match="timed out"):
        run_scan(
            job,
            env=fake_env(bin_dir, hang=True, ignore_sigterm=True),
            popen=popen,
            timeout_s=1.0,
        )

    assert popen.procs[0].returncode == -signal.SIGKILL
