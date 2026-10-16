"""A failed OCR run says why, from ocrmypdf's documented exit codes alone."""

import logging
from pathlib import Path

import pytest

from fastfoto_linux.documents.ocr import OcrStatus, run_ocr
from tests import _fake_ocrmypdf as fake
from tests.documents.ocr_helpers import PLAIN, TIMEOUT_S, run_fake

INSTALL = "sudo dnf install tesseract-langpack-eng tesseract-osd"


@pytest.fixture
def staging(tmp_path: Path) -> Path:
    folder = tmp_path / "staging"
    folder.mkdir()
    return folder


@pytest.fixture
def fake_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return fake.put_on_path(tmp_path / "bin", monkeypatch)


@pytest.mark.parametrize(
    ("code", "hint"),
    [
        (1, "--lang"),
        (2, "could not read"),
        (3, INSTALL),
        (4, "not a valid PDF"),
        (5, "permission"),
        (6, "already contain text"),
        (7, "run ocrmypdf"),
        (8, "encrypted"),
        (9, "configuration"),
        (10, "PDF/A"),
        (15, "does not name"),
        (130, "interrupted"),
    ],
)
def test_each_documented_exit_code_has_its_own_hint(
    fake_on_path: Path, staging: Path, monkeypatch: pytest.MonkeyPatch, code: int, hint: str
) -> None:
    outcome = run_fake(
        fake_on_path, monkeypatch, staging_parent=staging, mode="exit", exit_code=code
    )
    assert outcome.status is OcrStatus.FAILED
    assert outcome.pdf is None
    assert f"status {code}" in outcome.detail
    assert hint in outcome.detail


def test_a_missing_dependency_names_the_language_packs_asked_for(
    fake_on_path: Path, staging: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outcome = run_fake(
        fake_on_path, monkeypatch, staging_parent=staging, langs="eng+deu", mode="exit", exit_code=3
    )
    assert "sudo dnf install tesseract-langpack-eng tesseract-langpack-deu tesseract-osd" in (
        outcome.detail
    )


def test_a_code_nobody_documented_is_reported_as_it_is(
    fake_on_path: Path, staging: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outcome = run_fake(fake_on_path, monkeypatch, staging_parent=staging, mode="exit", exit_code=42)
    assert outcome.status is OcrStatus.FAILED
    assert "status 42" in outcome.detail


def test_a_process_killed_by_a_signal_says_which(
    fake_on_path: Path, staging: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outcome = run_fake(fake_on_path, monkeypatch, staging_parent=staging, mode="kill")
    assert outcome.status is OcrStatus.FAILED
    assert "signal 9" in outcome.detail


def test_the_hint_never_comes_from_what_the_tool_printed(
    fake_on_path: Path, staging: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outcome = run_fake(
        fake_on_path,
        monkeypatch,
        staging_parent=staging,
        mode="exit",
        exit_code=3,
        chatter="RECOGNISED-WORDS-1234",
    )
    assert "RECOGNISED-WORDS-1234" not in outcome.detail


def test_a_tool_that_cannot_be_started_is_not_logged_as_a_warning(
    caplog: pytest.LogCaptureFixture, staging: Path
) -> None:
    """The caller reports a failed OCR once; a second log line would repeat it."""
    caplog.set_level(logging.DEBUG)
    outcome = run_ocr(
        PLAIN,
        executable="/nonexistent/ocrmypdf",
        langs="eng",
        page_count=2,
        staging_parent=staging,
        timeout_s=TIMEOUT_S,
    )
    assert outcome.status is OcrStatus.FAILED
    assert not [record for record in caplog.records if record.levelno >= logging.WARNING]
