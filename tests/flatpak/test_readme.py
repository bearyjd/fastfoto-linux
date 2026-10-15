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
