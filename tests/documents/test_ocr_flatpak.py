"""Inside the Flatpak the OCR programs are the ones it brings: Tesseract in the app's own bin
folder, OCRmyPDF as the module of the app's interpreter. Nothing is installed from outside, so
no hint ever names brew, rpm-ostree, dnf or pip: a missing part means the bundle is broken."""

import os
import sys
from pathlib import Path

import pytest

from fastfoto_linux.documents import ocr_tools
from fastfoto_linux.documents.ocr_codes import MISSING_DEPENDENCY, describe_exit
from fastfoto_linux.documents.ocr_tools import (
    FLATPAK_BROKEN_HINT,
    find_ocrmypdf,
    find_tesseract,
    ocr_environment,
    ocr_fix_hint,
    ocr_fixes,
    ocr_install_hint,
    ocr_missing_text,
)
from fastfoto_linux.scanner import shim_trust
from tests import _fake_ocrmypdf as fake

OUTSIDE_COMMANDS = ("brew", "rpm-ostree", "dnf", "pip", "installer", "Homebrew")


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A Flatpak sandbox: the marker file exists, the app's bin folder is a folder of its own,
    and the PATH lists neither it nor anything else. Returns the app's bin folder."""
    marker = tmp_path / ".flatpak-info"
    marker.write_text("[Application]\n", encoding="utf-8")
    monkeypatch.setattr(shim_trust, "FLATPAK_INFO", marker)
    app_bin = tmp_path / "app" / "bin"
    app_bin.mkdir(parents=True)
    other = tmp_path / "usr" / "bin"
    other.mkdir(parents=True)
    monkeypatch.setattr(ocr_tools, "FLATPAK_BIN", app_bin)
    monkeypatch.setenv("PATH", str(other))
    return app_bin


def leave_the_sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shim_trust, "FLATPAK_INFO", tmp_path / "no-such-flatpak-info")


def test_the_bundled_tesseract_is_found_though_the_path_does_not_list_the_apps_folder(
    sandbox: Path,
) -> None:
    program = fake.install_tesseract(sandbox)
    assert find_tesseract() == str(program)


def test_the_bundled_tesseract_wins_over_one_on_the_path(
    sandbox: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundled = fake.install_tesseract(sandbox)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    fake.install_tesseract(elsewhere)
    monkeypatch.setenv("PATH", str(elsewhere))
    assert find_tesseract() == str(bundled)


def test_the_apps_folder_is_searched_only_inside_a_flatpak(
    sandbox: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake.install_tesseract(sandbox)
    leave_the_sandbox(tmp_path, monkeypatch)
    assert find_tesseract() is None
    assert str(sandbox) not in ocr_environment()["PATH"].split(os.pathsep)


def test_ocrmypdf_is_run_as_the_module_of_the_apps_interpreter(
    sandbox: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake.install_tesseract(sandbox)
    monkeypatch.setattr(ocr_tools, "OCR_MODULE", "json")  # stands for the bundled ocrmypdf
    assert find_ocrmypdf() == sys.executable


def test_the_environment_for_ocrmypdf_lists_the_apps_folder_first(sandbox: Path) -> None:
    folders = ocr_environment()["PATH"].split(os.pathsep)
    assert folders[0] == str(sandbox)


def test_homebrew_is_never_used_inside_a_flatpak(
    sandbox: Path, brew_bin: Path, brew_by_name: None
) -> None:
    fake.install_tesseract(brew_bin)
    assert find_tesseract() is None
    assert str(brew_bin) not in ocr_environment()["PATH"].split(os.pathsep)


def test_the_hint_is_one_text_that_says_the_bundle_is_broken() -> None:
    hint = FLATPAK_BROKEN_HINT
    assert "Flatpak" in hint
    assert "reinstall" in hint.lower()
    assert "broken" in hint.lower() or "missing" in hint.lower()


@pytest.mark.parametrize("command", OUTSIDE_COMMANDS)
def test_the_hint_names_no_command_that_installs_from_outside(command: str) -> None:
    assert command.lower() not in FLATPAK_BROKEN_HINT.lower()


@pytest.mark.parametrize(("ocrmypdf", "tesseract"), [(True, False), (False, True), (False, False)])
def test_whichever_part_is_missing_the_fix_is_to_reinstall_the_flatpak(
    sandbox: Path, monkeypatch: pytest.MonkeyPatch, *, ocrmypdf: bool, tesseract: bool
) -> None:
    monkeypatch.setattr(
        ocr_tools, "OCR_MODULE", "json" if ocrmypdf else "fastfoto_linux_no_such_module"
    )
    if tesseract:
        fake.install_tesseract(sandbox)
    assert ocr_missing_text().endswith("not installed")
    assert ocr_fix_hint() == FLATPAK_BROKEN_HINT
    assert {fix for _, fix in ocr_fixes()} == {FLATPAK_BROKEN_HINT}


def test_an_immutable_system_with_brew_does_not_change_what_a_flatpak_says(
    sandbox: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ostree: None
) -> None:
    brew = tmp_path / "usr" / "bin" / "brew"
    brew.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    brew.chmod(0o755)
    monkeypatch.setattr(ocr_tools, "BREW", "brew")
    assert ocr_install_hint() == FLATPAK_BROKEN_HINT


def test_outside_a_flatpak_the_hints_are_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    leave_the_sandbox(tmp_path, monkeypatch)
    assert ocr_install_hint() == ocr_tools.DNF_INSTALL_HINT
    assert FLATPAK_BROKEN_HINT not in ocr_fix_hint()


@pytest.mark.parametrize("langs", ["deu", "eng+deu", "fra+spa"])
def test_a_language_that_is_not_bundled_says_only_english_comes_with_the_flatpak(
    sandbox: Path, langs: str
) -> None:
    text = describe_exit(MISSING_DEPENDENCY, langs)
    assert "English" in text
    assert "eng" in text
    assert "Flatpak" in text
    for command in (*OUTSIDE_COMMANDS, "langpack"):
        assert command.lower() not in text.lower()


def test_when_english_itself_is_missing_the_bundle_is_broken(sandbox: Path) -> None:
    text = describe_exit(MISSING_DEPENDENCY, "eng")
    assert "reinstall" in text.lower()
    for command in OUTSIDE_COMMANDS:
        assert command.lower() not in text.lower()


def test_the_other_exit_codes_are_described_as_before(sandbox: Path) -> None:
    assert describe_exit(6, "eng") == (
        "ocrmypdf exited with status 6: the pages already contain text, so there was nothing to do"
    )
