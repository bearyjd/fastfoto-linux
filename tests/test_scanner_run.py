import stat
import subprocess
import sys
import textwrap
from collections.abc import Mapping
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest

from fastfoto_linux.scanner.errors import NoDocumentsError, ScanError, ScannerError
from fastfoto_linux.scanner.job import ScanJob, build_argv
from fastfoto_linux.scanner.run import ScanResult, run_scan

DEVICE = "epsonds:libusb:001:002"
SANE_STATUS_NO_DOCS = 7
SANE_STATUS_JAMMED = 6
SANE_STATUS_IO_ERROR = 9
OUT_OF_DOCS = "Document feeder out of documents"
ENV = {"PATH": "/nonexistent", "LANG": "C"}


class FakeRunner:
    """Stands in for subprocess.run: writes N pages following the --batch pattern in argv."""

    def __init__(
        self,
        *,
        pages: int = 0,
        returncode: int = 0,
        stderr: str | None = "",
        raises: BaseException | None = None,
        numbers: tuple[int, ...] | None = None,
    ) -> None:
        self.numbers = numbers if numbers is not None else tuple(range(1, pages + 1))
        self.returncode = returncode
        self.stderr = stderr
        self.raises = raises
        self.calls: list[tuple[tuple[str, ...], dict[str, Any]]] = []

    def __call__(self, argv: tuple[str, ...], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append((argv, kwargs))
        batch = next(a for a in argv if a.startswith("--batch=")).removeprefix("--batch=")
        for number in self.numbers:
            Path(batch % number).write_bytes(b"fake")
        if self.raises is not None:
            raise self.raises
        return subprocess.CompletedProcess(argv, self.returncode, stdout="", stderr=self.stderr)


@pytest.fixture
def job(tmp_path: Path) -> ScanJob:
    return ScanJob(device=DEVICE, output_dir=tmp_path / "scans")


def names(paths: tuple[Path, ...]) -> list[str]:
    return [p.name for p in paths]


# --- success -------------------------------------------------------------------------------


def test_success_returns_the_pages_in_order_and_the_exit_code(job: ScanJob) -> None:
    runner = FakeRunner(pages=3, stderr=f"Scanning page 3\n{OUT_OF_DOCS}\n")

    result = run_scan(job, env=ENV, runner=runner)

    assert names(result.pages) == ["page-0001.png", "page-0002.png", "page-0003.png"]
    assert all(page.parent == job.output_dir for page in result.pages)
    assert result.returncode == 0


def test_pages_are_sorted_by_number_not_by_text(job: ScanJob) -> None:
    runner = FakeRunner(numbers=(10000, 2, 9999, 1))

    result = run_scan(job, env=ENV, runner=runner)

    assert names(result.pages) == [
        "page-0001.png",
        "page-0002.png",
        "page-9999.png",
        "page-10000.png",
    ]


def test_only_pages_with_the_jobs_prefix_and_numbering_are_collected(tmp_path: Path) -> None:
    job = ScanJob(device=DEVICE, output_dir=tmp_path / "scans", file_prefix="batch")
    job.output_dir.mkdir()
    for name in ["page-0001.png", "batch-1.png", "batch-0001.png.part", "batch-0001.jpg", "x.txt"]:
        (job.output_dir / name).write_bytes(b"other")

    result = run_scan(job, env=ENV, runner=FakeRunner(pages=1))

    assert names(result.pages) == ["batch-0001.png"]


def test_output_dir_is_created_when_missing(tmp_path: Path) -> None:
    job = ScanJob(device=DEVICE, output_dir=tmp_path / "a" / "b" / "scans")

    result = run_scan(job, env=ENV, runner=FakeRunner(pages=1))

    assert job.output_dir.is_dir()
    assert len(result.pages) == 1


def test_percent_sign_in_output_dir_round_trips_through_the_batch_pattern(tmp_path: Path) -> None:
    job = ScanJob(device=DEVICE, output_dir=tmp_path / "100%done")

    result = run_scan(job, env=ENV, runner=FakeRunner(pages=2))

    assert names(result.pages) == ["page-0001.png", "page-0002.png"]
    assert all(page.parent == job.output_dir for page in result.pages)


def test_runner_is_called_with_argv_tuple_env_and_safe_subprocess_options(job: ScanJob) -> None:
    runner = FakeRunner(pages=1)
    env = {"PATH": "/usr/bin", "LD_PRELOAD": "/opt/shim.so"}

    run_scan(job, env=env, runner=runner, timeout_s=42.0)

    ((argv, kwargs),) = runner.calls
    assert argv == build_argv(job)
    assert isinstance(argv, tuple)
    assert kwargs["env"] == env
    assert kwargs["timeout"] == 42.0
    assert kwargs["check"] is False
    assert kwargs["capture_output"] is True
    assert kwargs["stdin"] == subprocess.DEVNULL
    assert not kwargs.get("shell", False)


def test_env_mapping_is_not_mutated(job: ScanJob) -> None:
    env = {"PATH": "/usr/bin"}

    run_scan(job, env=env, runner=FakeRunner(pages=1))

    assert env == {"PATH": "/usr/bin"}


def test_timeout_none_means_no_timeout(job: ScanJob) -> None:
    runner = FakeRunner(pages=1)

    run_scan(job, env=ENV, runner=runner, timeout_s=None)

    assert runner.calls[0][1]["timeout"] is None


def test_scan_result_is_frozen() -> None:
    result = ScanResult(pages=(), returncode=0)

    with pytest.raises(FrozenInstanceError):
        result.returncode = 1  # type: ignore[misc]


# --- refusing to overwrite -----------------------------------------------------------------


def test_existing_batch_files_are_refused_and_the_runner_is_never_called(job: ScanJob) -> None:
    job.output_dir.mkdir()
    (job.output_dir / "page-0001.png").write_bytes(b"old")
    runner = FakeRunner(pages=1)

    with pytest.raises(FileExistsError, match="page-"):
        run_scan(job, env=ENV, runner=runner)

    assert runner.calls == []
    assert (job.output_dir / "page-0001.png").read_bytes() == b"old"


# --- end of stack and failures -------------------------------------------------------------


def test_empty_feeder_exit_status_7_without_pages_raises_no_documents(job: ScanJob) -> None:
    runner = FakeRunner(
        returncode=SANE_STATUS_NO_DOCS, stderr=f"scanimage: sane_start: {OUT_OF_DOCS}"
    )

    with pytest.raises(NoDocumentsError):
        run_scan(job, env=ENV, runner=runner)


def test_no_documents_is_detected_from_the_message_when_the_status_differs(job: ScanJob) -> None:
    runner = FakeRunner(returncode=1, stderr=f"scanimage: sane_start: {OUT_OF_DOCS}\n")

    with pytest.raises(NoDocumentsError):
        run_scan(job, env=ENV, runner=runner)


def test_localized_no_documents_is_still_detected_by_exit_status(job: ScanJob) -> None:
    runner = FakeRunner(returncode=SANE_STATUS_NO_DOCS, stderr="scanimage: sane_start: Zufuhr leer")

    with pytest.raises(NoDocumentsError):
        run_scan(job, env=ENV, runner=runner)


def test_exit_status_7_after_some_pages_is_a_normal_end_of_the_stack(job: ScanJob) -> None:
    runner = FakeRunner(pages=2, returncode=SANE_STATUS_NO_DOCS, stderr=OUT_OF_DOCS)

    result = run_scan(job, env=ENV, runner=runner)

    assert len(result.pages) == 2
    assert result.returncode == SANE_STATUS_NO_DOCS


def test_other_failure_without_pages_raises_scan_error_with_the_last_five_stderr_lines(
    job: ScanJob,
) -> None:
    stderr = "".join(f"line {i}\n" for i in range(1, 8)) + "\n  \n"
    runner = FakeRunner(returncode=SANE_STATUS_IO_ERROR, stderr=stderr)

    with pytest.raises(ScanError) as excinfo:
        run_scan(job, env=ENV, runner=runner)

    message = str(excinfo.value)
    assert all(f"line {i}" in message for i in range(3, 8))
    assert "line 1" not in message
    assert "line 2" not in message
    assert str(SANE_STATUS_IO_ERROR) in message
    assert excinfo.value.returncode == SANE_STATUS_IO_ERROR
    assert excinfo.value.pages == ()


def test_failure_after_some_pages_raises_scan_error_that_keeps_the_finished_pages(
    job: ScanJob,
) -> None:
    runner = FakeRunner(
        pages=2, returncode=SANE_STATUS_JAMMED, stderr="sane_start: Document feeder jammed"
    )

    with pytest.raises(ScanError) as excinfo:
        run_scan(job, env=ENV, runner=runner)

    assert names(excinfo.value.pages) == ["page-0001.png", "page-0002.png"]
    assert excinfo.value.returncode == SANE_STATUS_JAMMED
    assert "jammed" in str(excinfo.value)


def test_exit_zero_without_any_page_is_an_error_not_a_silent_success(job: ScanJob) -> None:
    with pytest.raises(ScanError, match="no pages"):
        run_scan(job, env=ENV, runner=FakeRunner(returncode=0))


def test_missing_stderr_is_tolerated(job: ScanJob) -> None:
    runner = FakeRunner(returncode=SANE_STATUS_IO_ERROR, stderr=None)

    with pytest.raises(ScanError):
        run_scan(job, env=ENV, runner=runner)


def test_timeout_raises_scan_error_and_keeps_pages_written_so_far(job: ScanJob) -> None:
    runner = FakeRunner(pages=1, raises=subprocess.TimeoutExpired(cmd="scanimage", timeout=5))

    with pytest.raises(ScanError, match="timed out") as excinfo:
        run_scan(job, env=ENV, runner=runner, timeout_s=5.0)

    assert names(excinfo.value.pages) == ["page-0001.png"]
    assert excinfo.value.returncode is None
    assert isinstance(excinfo.value.__cause__, subprocess.TimeoutExpired)


def test_scanimage_that_cannot_be_started_raises_scan_error(job: ScanJob) -> None:
    runner = FakeRunner(raises=FileNotFoundError(2, "No such file or directory", "scanimage"))

    with pytest.raises(ScanError, match="could not start scanimage") as excinfo:
        run_scan(job, env=ENV, runner=runner)

    assert isinstance(excinfo.value.__cause__, FileNotFoundError)


def test_every_failure_is_a_scanner_error(job: ScanJob) -> None:
    for runner in (
        FakeRunner(returncode=SANE_STATUS_NO_DOCS),
        FakeRunner(returncode=SANE_STATUS_IO_ERROR),
    ):
        with pytest.raises(ScannerError):
            run_scan(job, env=ENV, runner=runner)


# --- the default runner (a real subprocess against a fake scanimage) ------------------------


def write_fake_scanimage(bin_dir: Path, *, pages: int, exit_code: int) -> None:
    bin_dir.mkdir()
    script = bin_dir / "scanimage"
    script.write_text(
        textwrap.dedent(
            f"""\
            #!{sys.executable}
            import sys
            batch = next(a for a in sys.argv if a.startswith("--batch=")).split("=", 1)[1]
            for n in range(1, {pages} + 1):
                open(batch % n, "wb").write(b"fake")
            sys.stderr.write("Batch terminated\\nscanimage: sane_start: {OUT_OF_DOCS}\\n")
            sys.exit({exit_code})
            """
        )
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)


def fake_env(bin_dir: Path) -> Mapping[str, str]:
    return {"PATH": str(bin_dir), "LANG": "C"}


def test_default_runner_runs_a_real_subprocess_and_parses_its_exit_status(
    job: ScanJob, tmp_path: Path
) -> None:
    write_fake_scanimage(tmp_path / "bin", pages=2, exit_code=0)

    result = run_scan(job, env=fake_env(tmp_path / "bin"), timeout_s=30.0)

    assert names(result.pages) == ["page-0001.png", "page-0002.png"]
    assert result.returncode == 0


def test_default_runner_maps_exit_status_7_without_pages_to_no_documents(
    job: ScanJob, tmp_path: Path
) -> None:
    write_fake_scanimage(tmp_path / "bin", pages=0, exit_code=SANE_STATUS_NO_DOCS)

    with pytest.raises(NoDocumentsError):
        run_scan(job, env=fake_env(tmp_path / "bin"), timeout_s=30.0)


def test_default_runner_reports_a_missing_scanimage_as_scan_error(
    job: ScanJob, tmp_path: Path
) -> None:
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()

    with pytest.raises(ScanError, match="could not start scanimage"):
        run_scan(job, env=fake_env(empty_bin), timeout_s=30.0)
