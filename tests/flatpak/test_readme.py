"""The README tells how to build, install, run and remove the Flatpak."""

import re

from tests.flatpak.helpers import APP_ID, ROOT

README = ROOT / "README.md"


def section() -> str:
    text = README.read_text()
    match = re.search(r"^##+ Flatpak\b.*?(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    assert match, "the README has no Flatpak section"
    return match.group(0)


def test_the_flatpak_section_has_build_install_run_and_uninstall_commands() -> None:
    text = section()
    assert "flatpak-builder" in text
    assert "packaging/flatpak/io.github.bearyjd.FastFotoLinux.yml" in text
    assert "flatpak --user install" in text or "flatpak install --user" in text
    assert f"flatpak run {APP_ID}" in text
    assert f"--command=ffscan {APP_ID}" in text or f"{APP_ID} --command=ffscan" in text
    assert "flatpak uninstall" in text


def test_the_readme_no_longer_says_the_flatpak_is_still_to_come() -> None:
    text = README.read_text()
    assert "Flatpak, which brings its own Qt and Kirigami, is coming" not in text
    assert "Flatpak to come" not in text


def test_the_readme_names_no_personal_paths() -> None:
    assert not re.search(r"/(?:var/)?home/\w", README.read_text())


def plain_section() -> str:
    """The Flatpak section with its line breaks gone, so a sentence can be searched for."""
    return " ".join(section().split())


def test_the_readme_says_plainly_what_device_all_exposes_and_why() -> None:
    text = plain_section()
    assert "--device=all" in text
    assert "all device nodes" in text
    assert "libusb" in text
    assert "USB portal" in text


def test_the_readme_names_what_the_base_app_adds_to_the_sandbox() -> None:
    text = plain_section()
    assert "session-bus" in text or "session bus" in text
    assert "xdg-config/kdeglobals:ro" in text
    assert "io.qt.PySide.BaseApp" in text


def test_the_readme_says_why_the_pictures_folder_is_granted() -> None:
    text = plain_section()
    assert "Pictures" in text
    assert "file locks" in text


def test_the_readme_does_not_say_photos_go_to_pictures_by_default() -> None:
    text = plain_section()
    assert "normally" not in text  # the output folder starts empty; the user chooses it
    assert "any folder under Pictures" in text
    assert "folder dialog" in text
