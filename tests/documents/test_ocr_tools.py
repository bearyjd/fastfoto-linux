"""Where the OCR programs are found and in what order, and what to install when one is missing."""

import os
import sys
from pathlib import Path

import pytest

from fastfoto_linux.documents import ocr_tools
from fastfoto_linux.documents.ocr_tools import (
    BREW_INSTALL_HINT,
    DNF_INSTALL_HINT,
    find_ocrmypdf,
    find_tesseract,
    locate_ocrmypdf,
    ocr_environment,
    ocr_install_hint,
    uses_homebrew,
)


def program(folder: Path, name: str) -> str:
    """A program that does nothing, in ``folder``; returns its path."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)
    return str(path)


@pytest.fixture
def on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The only folder on PATH."""
    folder = tmp_path / "on-path"
    folder.mkdir()
    monkeypatch.setenv("PATH", str(folder))
    return folder


@pytest.fixture
def brew_bin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A Homebrew bin folder, which is not on PATH."""
    folder = tmp_path / "linuxbrew" / "bin"
    folder.mkdir(parents=True)
    monkeypatch.setattr(ocr_tools, "BREW_BIN", folder)
    return folder


@pytest.fixture
def brew_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """``brew`` is looked for by its real name (tests/conftest.py gives it one nobody has)."""
    monkeypatch.setattr(ocr_tools, "BREW", "brew")


@pytest.fixture
def ostree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    marker = tmp_path / "ostree-booted"
    marker.touch()
    monkeypatch.setattr(ocr_tools, "OSTREE_MARKER", marker)


@pytest.fixture
def importable(monkeypatch: pytest.MonkeyPatch) -> None:
    """The running interpreter can import the module that stands for ocrmypdf."""
    monkeypatch.setattr(ocr_tools, "OCR_MODULE", "json")


# ---- ocrmypdf: the interpreter's own module, then PATH, then Homebrew's folder --------------


def test_ocrmypdf_that_is_nowhere_is_none(on_path: Path, brew_bin: Path) -> None:
    assert locate_ocrmypdf() is None


def test_the_module_in_the_running_interpreter_comes_first(
    on_path: Path, brew_bin: Path, importable: None
) -> None:
    program(on_path, "ocrmypdf")
    program(brew_bin, "ocrmypdf")
    assert locate_ocrmypdf() == sys.executable


def test_without_the_module_ocrmypdf_on_path_comes_before_the_one_in_the_brew_folder(
    on_path: Path, brew_bin: Path
) -> None:
    wanted = program(on_path, "ocrmypdf")
    program(brew_bin, "ocrmypdf")
    assert locate_ocrmypdf() == wanted


def test_the_brew_folder_is_the_last_place_ocrmypdf_is_looked_for(
    on_path: Path, brew_bin: Path
) -> None:
    assert locate_ocrmypdf() is None
    wanted = program(brew_bin, "ocrmypdf")
    assert locate_ocrmypdf() == wanted


def test_a_brew_folder_that_does_not_exist_is_not_an_error(on_path: Path) -> None:
    assert not ocr_tools.BREW_BIN.exists()
    assert locate_ocrmypdf() is None
    assert find_tesseract() is None


# ---- Tesseract: PATH, then Homebrew's folder ----------------------------------------------------


def test_tesseract_on_path_comes_before_the_one_in_the_brew_folder(
    on_path: Path, brew_bin: Path
) -> None:
    program(brew_bin, "tesseract")
    wanted = program(on_path, "tesseract")
    assert find_tesseract() == wanted


def test_tesseract_is_found_in_the_brew_folder_when_path_has_none(
    on_path: Path, brew_bin: Path
) -> None:
    assert find_tesseract() is None
    wanted = program(brew_bin, "tesseract")
    assert find_tesseract() == wanted


# ---- OCR is available only where both are ---------------------------------------------------


def test_ocr_needs_tesseract_as_well_as_ocrmypdf(on_path: Path, brew_bin: Path) -> None:
    wanted = program(on_path, "ocrmypdf")
    assert locate_ocrmypdf() == wanted
    assert find_ocrmypdf() is None  # not a crash: OCR is unavailable and the hint says why
    program(brew_bin, "tesseract")
    assert find_ocrmypdf() == wanted


def test_the_module_needs_tesseract_too(on_path: Path, brew_bin: Path, importable: None) -> None:
    assert find_ocrmypdf() is None
    program(brew_bin, "tesseract")
    assert find_ocrmypdf() == sys.executable


def test_tesseract_alone_is_not_ocr(on_path: Path) -> None:
    program(on_path, "tesseract")
    assert find_ocrmypdf() is None


# ---- the environment ocrmypdf runs in --------------------------------------------------------


def test_path_leads_with_the_brew_folder_then_the_interpreters_folder(
    brew_bin: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    folders = ocr_environment()["PATH"].split(os.pathsep)
    assert folders == [str(brew_bin), str(Path(sys.executable).parent), "/usr/bin", "/bin"]


def test_a_brew_folder_that_does_not_exist_is_left_out_of_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", "/usr/bin")
    folders = ocr_environment()["PATH"].split(os.pathsep)
    assert folders == [str(Path(sys.executable).parent), "/usr/bin"]


def test_the_environment_is_a_copy_with_everything_else_kept(
    brew_bin: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("FASTFOTO_TEST_VARIABLE", "kept")
    before = dict(os.environ)
    made = ocr_environment()
    assert made["FASTFOTO_TEST_VARIABLE"] == "kept"
    assert made is not os.environ
    assert dict(os.environ) == before


def test_an_environment_without_path_still_gets_the_folders(
    brew_bin: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PATH")
    folders = ocr_environment()["PATH"].split(os.pathsep)
    assert folders == [str(brew_bin), str(Path(sys.executable).parent)]


# ---- what to install, per kind of system -------------------------------------------------------


def test_the_hints_are_the_documented_commands() -> None:
    assert BREW_INSTALL_HINT == "brew install tesseract"
    assert ocr_tools.BREW_LANG_HINT == "brew install tesseract-lang"
    assert DNF_INSTALL_HINT == "sudo dnf install tesseract tesseract-osd"


def test_a_classic_system_installs_tesseract_with_dnf(on_path: Path) -> None:
    assert not uses_homebrew()
    assert ocr_install_hint() == DNF_INSTALL_HINT


def test_an_immutable_system_installs_tesseract_with_brew(on_path: Path, ostree: None) -> None:
    assert uses_homebrew()
    assert ocr_install_hint() == BREW_INSTALL_HINT


def test_a_system_with_brew_installs_tesseract_with_brew(
    on_path: Path, brew_bin: Path, brew_by_name: None
) -> None:
    assert not uses_homebrew()  # a folder is not brew
    program(brew_bin, "brew")
    assert uses_homebrew()
    assert ocr_install_hint() == BREW_INSTALL_HINT


def test_brew_on_path_counts(on_path: Path, brew_by_name: None) -> None:
    program(on_path, "brew")
    assert ocr_install_hint() == BREW_INSTALL_HINT
