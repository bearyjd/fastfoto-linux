"""OCR is staged in a private temporary folder outside the output folder, gone on every path."""

import os
import signal
import tempfile
import threading
from pathlib import Path

import pytest

from fastfoto_linux.documents.errors import OcrCancelledError
from fastfoto_linux.documents.ocr import OcrStatus, run_ocr
from tests import _fake_ocrmypdf as fake
from tests.documents.ocr_helpers import PLAIN, SHORT_GRACE_S, TIMEOUT_S, run_fake

PRIVATE = 0o700


@pytest.fixture
def temp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The system temporary folder, for this test only."""
    folder = tmp_path / "system-tmp"
    folder.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(folder))
    return folder


@pytest.fixture
def fake_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return fake.put_on_path(tmp_path / "bin", monkeypatch)


def test_the_staging_folder_is_private_and_in_the_system_temporary_folder(
    fake_on_path: Path, temp: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = tmp_path / "record.json"
    outcome = run_fake(fake_on_path, monkeypatch, record_to=str(record))
    seen = fake.read_record(record)
    assert outcome.status is OcrStatus.DONE
    assert Path(seen["staging_dir"]).parent == temp
    assert seen["staging_mode"] == PRIVATE


@pytest.mark.parametrize(
    "spec",
    [
        {},
        {"mode": "exit", "exit_code": 3},
        {"mode": "garbage"},
        {"mode": "kill"},
        {"mode": "hang"},
    ],
    ids=["done", "failed", "unusable-result", "killed", "timed-out"],
)
def test_nothing_is_left_in_the_temporary_folder_after_an_outcome(
    fake_on_path: Path, temp: Path, monkeypatch: pytest.MonkeyPatch, spec: dict
) -> None:
    run_fake(fake_on_path, monkeypatch, **spec)
    assert list(temp.iterdir()) == []


def test_nothing_is_left_after_cancelling(
    fake_on_path: Path, temp: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = tmp_path / "record.json"
    fake.configure(monkeypatch, mode="hang", record_to=str(record))
    cancel = threading.Event()
    fake.when_started(record, cancel.set)
    with pytest.raises(OcrCancelledError):
        run_ocr(
            PLAIN,
            executable=str(fake_on_path),
            langs="eng",
            page_count=2,
            timeout_s=TIMEOUT_S,
            grace_s=SHORT_GRACE_S,
            cancel=cancel,
        )
    assert list(temp.iterdir()) == []


def test_nothing_is_left_after_ctrl_c(
    fake_on_path: Path, temp: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = tmp_path / "record.json"
    fake.configure(monkeypatch, mode="hang", record_to=str(record))
    fake.when_started(record, lambda: os.kill(os.getpid(), signal.SIGINT))
    with pytest.raises(KeyboardInterrupt):
        run_ocr(
            PLAIN,
            executable=str(fake_on_path),
            langs="eng",
            page_count=2,
            timeout_s=TIMEOUT_S,
            grace_s=SHORT_GRACE_S,
        )
    assert list(temp.iterdir()) == []
