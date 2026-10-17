"""Homebrew's folder is used only when nobody else could have put a program in it, and what the
OCR run finds there is what detection found."""

import logging
import os
import shutil
from pathlib import Path

import pytest

from fastfoto_linux.documents import ocr_tools
from fastfoto_linux.documents.ocr_tools import (
    BREW_INSTALL_HINT,
    DNF_INSTALL_HINT,
    brew_folder_problem,
    find_tesseract,
    ocr_environment,
    ocr_install_hint,
    uses_homebrew,
)
from tests.documents.ocr_helpers import program

ME = 1000
ROOT = 0
STRANGER = 4242


def make_folder(path: Path, mode: int) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(mode)
    return path


@pytest.fixture
def brew_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Homebrew's folder, with a tesseract and a brew in it; the test sets its permissions."""
    folder = tmp_path / "linuxbrew" / "bin"
    program(folder, "tesseract")
    program(folder, "brew")
    monkeypatch.setattr(ocr_tools, "BREW_BIN", folder)
    return folder


# ---- the rule, as a function of the folder's mode and owner ---------------------------------


@pytest.mark.parametrize("mode", [0o755, 0o700, 0o750, 0o555])
@pytest.mark.parametrize("owner", [ME, ROOT])
def test_a_folder_of_root_or_the_user_that_nobody_else_can_write_to_is_trusted(
    mode: int, owner: int
) -> None:
    assert brew_folder_problem(mode, owner, ME) is None


@pytest.mark.parametrize("mode", [0o777, 0o775, 0o757, 0o770, 0o722, 0o752])
def test_a_folder_that_the_group_or_anyone_can_write_to_is_not(mode: int) -> None:
    assert "writable" in (brew_folder_problem(mode, ME, ME) or "")


def test_a_folder_of_someone_else_is_not() -> None:
    assert "owned by" in (brew_folder_problem(0o755, STRANGER, ME) or "")


def test_root_is_trusted_whoever_runs_the_program() -> None:
    assert brew_folder_problem(0o755, ROOT, STRANGER) is None


# ---- the real folder: found, used, or ignored ---------------------------------------------------


def test_a_private_folder_is_used(brew_folder: Path) -> None:
    brew_folder.chmod(0o755)
    assert find_tesseract() == str(brew_folder / "tesseract")
    assert str(brew_folder) in ocr_environment()["PATH"].split(os.pathsep)


@pytest.mark.parametrize("mode", [0o777, 0o775, 0o757])
def test_a_folder_others_can_write_to_is_ignored_by_detection_and_by_the_run(
    brew_folder: Path, mode: int
) -> None:
    brew_folder.chmod(mode)
    assert find_tesseract() is None
    assert str(brew_folder) not in ocr_environment()["PATH"].split(os.pathsep)


def test_a_folder_others_can_write_to_does_not_make_brew_available(
    brew_folder: Path, brew_by_name: None
) -> None:
    brew_folder.chmod(0o777)
    assert not uses_homebrew()
    assert ocr_install_hint() == DNF_INSTALL_HINT  # the normal hint, not a command that is not run
    brew_folder.chmod(0o755)
    assert ocr_install_hint() == BREW_INSTALL_HINT


def test_the_reason_is_in_the_debug_log(
    brew_folder: Path, caplog: pytest.LogCaptureFixture
) -> None:
    brew_folder.chmod(0o777)
    with caplog.at_level(logging.DEBUG, logger=ocr_tools.__name__):
        assert find_tesseract() is None
    messages = [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]
    assert any(str(brew_folder) in m and "writable" in m for m in messages)
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_a_folder_that_is_not_there_is_ignored_without_a_word(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(ocr_tools, "BREW_BIN", tmp_path / "nowhere")
    with caplog.at_level(logging.DEBUG, logger=ocr_tools.__name__):
        assert find_tesseract() is None
        assert str(tmp_path / "nowhere") not in ocr_environment()["PATH"]
    assert caplog.records == []


# ---- detection and the run resolve the same program --------------------------------------------


def test_a_tesseract_earlier_on_path_wins_for_the_run_as_it_does_for_detection(
    on_path: Path, brew_bin: Path
) -> None:
    program(brew_bin, "tesseract")
    wanted = program(on_path, "tesseract")
    assert find_tesseract() == wanted
    assert shutil.which("tesseract", path=ocr_environment()["PATH"]) == wanted


def test_a_tesseract_only_in_the_brew_folder_is_the_one_both_find(
    on_path: Path, brew_bin: Path
) -> None:
    wanted = program(brew_bin, "tesseract")
    assert find_tesseract() == wanted
    assert shutil.which("tesseract", path=ocr_environment()["PATH"]) == wanted
