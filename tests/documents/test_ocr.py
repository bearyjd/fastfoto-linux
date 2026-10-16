"""The OCR runner: a fake ``ocrmypdf`` on PATH stands in for the real tool."""

import io
import os
import signal
import threading
import time
from pathlib import Path

import img2pdf
import numpy as np
import pytest
from PIL import Image

from fastfoto_linux.documents.errors import OcrCancelledError
from fastfoto_linux.documents.ocr import (
    OcrOutcome,
    OcrStatus,
    find_ocrmypdf,
    run_ocr,
    validate_langs,
)
from tests import _fake_ocrmypdf as fake

TIMEOUT_S = 20.0
SHORT_TIMEOUT_S = 0.6
SHORT_GRACE_S = 0.4


def jpeg(seed: int) -> bytes:
    pixels = np.random.default_rng(seed).integers(0, 256, (40, 30, 3), dtype=np.uint8)
    buffer = io.BytesIO()
    Image.fromarray(pixels).save(buffer, "JPEG", dpi=(100, 100))
    return buffer.getvalue()


PLAIN = img2pdf.convert(jpeg(1), jpeg(2))
ONE_PAGE = img2pdf.convert(jpeg(3))


@pytest.fixture
def staging(tmp_path: Path) -> Path:
    folder = tmp_path / "out"
    folder.mkdir()
    return folder


@pytest.fixture
def fake_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return fake.put_on_path(tmp_path / "bin", monkeypatch)


def run(
    staging: Path,
    executable: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    langs: str = "eng",
    **spec: object,
) -> OcrOutcome:
    fake.configure(monkeypatch, **spec)
    return run_ocr(
        PLAIN,
        executable=str(executable),
        langs=langs,
        page_count=2,
        staging_parent=staging,
        timeout_s=TIMEOUT_S,
    )


def alive(record: dict, *names: str) -> list[int]:
    return [record[n] for n in names if record.get(n) and fake.process_alive(record[n])]


# ---- languages and discovery --------------------------------------------------------------


@pytest.mark.parametrize("langs", ["eng", "eng+deu", "chi_sim", "deu_frak+eng+fra"])
def test_tesseract_language_codes_are_accepted(langs: str) -> None:
    assert validate_langs(langs) == langs


@pytest.mark.parametrize(
    "langs",
    ["", "ENG", "eng+", "+eng", "eng deu", "eng;rm -rf /", "eng+deu+", "../x", "eng\n", "e1"],
)
def test_anything_else_is_refused(langs: str) -> None:
    with pytest.raises(ValueError, match="language"):
        validate_langs(langs)


def test_ocrmypdf_is_found_on_path_or_not_at_all(
    fake_on_path: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert find_ocrmypdf() == str(fake_on_path)
    monkeypatch.setenv("PATH", str(tmp_path))
    assert find_ocrmypdf() is None


# ---- a normal run -------------------------------------------------------------------------


def test_it_runs_the_documented_command_on_a_staging_copy_and_returns_the_result(
    fake_on_path: Path, staging: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = tmp_path / "record.json"
    outcome = run(
        staging, fake_on_path, monkeypatch, mode="mark", record_to=str(record), langs="eng+deu"
    )
    seen = fake.read_record(record)
    source, target = Path(seen["argv"][-2]), Path(seen["argv"][-1])
    assert seen["argv"][:-2] == ["--output-type", "pdf", "--rotate-pages", "-l", "eng+deu"]
    assert source.parent == target.parent
    assert source.parent.parent == staging
    assert source.parent.name.startswith(".")
    assert outcome.status is OcrStatus.DONE
    assert outcome.pdf == PLAIN + fake.MARKER


def test_the_staging_folder_is_gone_afterwards(
    fake_on_path: Path, staging: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run(staging, fake_on_path, monkeypatch)
    assert list(staging.iterdir()) == []


def test_the_staged_input_is_the_plain_pdf(
    fake_on_path: Path, staging: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert run(staging, fake_on_path, monkeypatch).pdf == PLAIN  # the fake copies its input


def test_recognised_text_is_never_logged_or_printed(
    fake_on_path: Path,
    staging: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capfd: pytest.CaptureFixture[str],
) -> None:
    caplog.set_level("DEBUG")
    run(staging, fake_on_path, monkeypatch, chatter="RECOGNISED-WORDS-1234")
    captured = capfd.readouterr()
    assert "RECOGNISED-WORDS-1234" not in caplog.text + captured.out + captured.err


def test_a_bad_language_stops_before_anything_is_launched(
    fake_on_path: Path, staging: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = tmp_path / "record.json"
    with pytest.raises(ValueError, match="language"):
        run(staging, fake_on_path, monkeypatch, record_to=str(record), langs="eng;touch x")
    assert not record.exists()


# ---- problems end as an outcome, never a lost scan ---------------------------------------


@pytest.mark.parametrize("mode", ["empty", "no_output", "garbage"])
def test_an_unusable_result_is_a_failure(
    fake_on_path: Path, staging: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    outcome = run(staging, fake_on_path, monkeypatch, mode=mode)
    assert outcome.status is OcrStatus.FAILED
    assert outcome.pdf is None
    assert list(staging.iterdir()) == []


def test_a_result_with_the_wrong_page_count_is_a_failure(
    fake_on_path: Path, staging: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outcome = run(staging, fake_on_path, monkeypatch, mode="short", short_pdf_hex=ONE_PAGE.hex())
    assert outcome.status is OcrStatus.FAILED
    assert "page" in outcome.detail


def test_a_non_zero_exit_is_a_failure_that_names_the_status(
    fake_on_path: Path, staging: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outcome = run(staging, fake_on_path, monkeypatch, mode="fail")
    assert outcome.status is OcrStatus.FAILED
    assert "2" in outcome.detail
    assert list(staging.iterdir()) == []


def test_a_missing_executable_is_a_failure_not_a_crash(staging: Path) -> None:
    outcome = run_ocr(
        PLAIN,
        executable="/nonexistent/ocrmypdf",
        langs="eng",
        page_count=2,
        staging_parent=staging,
        timeout_s=TIMEOUT_S,
    )
    assert outcome.status is OcrStatus.FAILED


def test_a_staging_folder_that_cannot_be_made_is_a_failure_not_a_crash(
    fake_on_path: Path, tmp_path: Path
) -> None:
    outcome = run_ocr(
        PLAIN,
        executable=str(fake_on_path),
        langs="eng",
        page_count=2,
        staging_parent=tmp_path / "missing",
        timeout_s=TIMEOUT_S,
    )
    assert outcome.status is OcrStatus.FAILED


# ---- time limit, cancel and interrupt: nothing is left running or behind -------------------


def test_a_run_that_takes_too_long_is_stopped_and_cleaned_up(
    fake_on_path: Path, staging: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = tmp_path / "record.json"
    fake.configure(monkeypatch, mode="hang", record_to=str(record), child=True)
    started = time.monotonic()
    outcome = run_ocr(
        PLAIN,
        executable=str(fake_on_path),
        langs="eng",
        page_count=2,
        staging_parent=staging,
        timeout_s=SHORT_TIMEOUT_S,
        grace_s=SHORT_GRACE_S,
    )
    assert outcome.status is OcrStatus.TIMED_OUT
    assert time.monotonic() - started < 5
    assert alive(fake.read_record(record), "pid", "child") == []
    assert list(staging.iterdir()) == []


def test_a_process_that_ignores_sigterm_is_killed_after_the_grace_period(
    fake_on_path: Path, staging: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = tmp_path / "record.json"
    fake.configure(monkeypatch, mode="hang", record_to=str(record), child=True, ignore_sigterm=True)
    started = time.monotonic()
    outcome = run_ocr(
        PLAIN,
        executable=str(fake_on_path),
        langs="eng",
        page_count=2,
        staging_parent=staging,
        timeout_s=SHORT_TIMEOUT_S,
        grace_s=SHORT_GRACE_S,
    )
    assert outcome.status is OcrStatus.TIMED_OUT
    assert time.monotonic() - started >= SHORT_TIMEOUT_S + SHORT_GRACE_S * 0.9  # it waited
    assert alive(fake.read_record(record), "pid", "child") == []


def test_cancelling_stops_ocr_and_raises(
    fake_on_path: Path, staging: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = tmp_path / "record.json"
    fake.configure(monkeypatch, mode="hang", record_to=str(record), child=True)
    cancel = threading.Event()
    threading.Timer(0.3, cancel.set).start()
    with pytest.raises(OcrCancelledError):
        run_ocr(
            PLAIN,
            executable=str(fake_on_path),
            langs="eng",
            page_count=2,
            staging_parent=staging,
            timeout_s=TIMEOUT_S,
            grace_s=SHORT_GRACE_S,
            cancel=cancel,
        )
    assert alive(fake.read_record(record), "pid", "child") == []
    assert list(staging.iterdir()) == []


def test_ctrl_c_stops_ocr_cleans_up_and_is_not_swallowed(
    fake_on_path: Path, staging: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = tmp_path / "record.json"
    fake.configure(monkeypatch, mode="hang", record_to=str(record), child=True)
    timer = threading.Timer(0.4, lambda: os.kill(os.getpid(), signal.SIGINT))
    timer.start()
    try:
        with pytest.raises(KeyboardInterrupt):
            run_ocr(
                PLAIN,
                executable=str(fake_on_path),
                langs="eng",
                page_count=2,
                staging_parent=staging,
                timeout_s=TIMEOUT_S,
                grace_s=SHORT_GRACE_S,
            )
    finally:
        timer.cancel()
    assert alive(fake.read_record(record), "pid", "child") == []
    assert list(staging.iterdir()) == []
