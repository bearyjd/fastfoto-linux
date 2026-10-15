"""What the Flatpak exports to the desktop: the launcher, the icon and the AppStream metadata."""

import re
import shutil
import subprocess
import tomllib
import xml.etree.ElementTree as ET
from configparser import ConfigParser

import pytest

from tests.flatpak.helpers import APP_ID, DESKTOP, ICON, METAINFO, ROOT


def metainfo() -> ET.Element:
    assert METAINFO.is_file(), f"{METAINFO.relative_to(ROOT)} does not exist"
    return ET.parse(METAINFO).getroot()


def test_the_launcher_runs_the_bare_command_so_flatpak_can_wrap_it() -> None:
    parser = ConfigParser(interpolation=None, delimiters=("=",))
    parser.optionxform = str  # type: ignore[assignment,method-assign]
    parser.read(DESKTOP, encoding="utf-8")
    entry = parser["Desktop Entry"]
    assert entry["Exec"] == "fastfoto"
    assert entry["Icon"] == APP_ID
    assert "/" not in entry["Exec"]
    assert ICON.is_file()


def test_the_metainfo_is_for_the_desktop_application_with_the_same_id() -> None:
    root = metainfo()
    assert root.tag == "component"
    assert root.get("type") == "desktop-application"
    assert root.findtext("id") == APP_ID
    assert root.findtext("launchable") == f"{APP_ID}.desktop"
    assert root.find("launchable").get("type") == "desktop-id"  # type: ignore[union-attr]


def test_the_metainfo_names_the_licences_and_the_project_page() -> None:
    root = metainfo()
    assert root.findtext("project_license") == "GPL-3.0-or-later"
    assert root.findtext("metadata_license") == "CC0-1.0"
    url = root.find("url[@type='homepage']")
    assert url is not None
    assert url.text == "https://github.com/bearyjd/fastfoto-linux"


def test_the_metainfo_has_the_current_release_and_a_content_rating() -> None:
    root = metainfo()
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    release = root.find("releases/release")
    assert release is not None
    assert release.get("version") == version
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", release.get("date", ""))
    assert root.find("content_rating[@type='oars-1.1']") is not None


def test_the_metainfo_carries_no_personal_contact_details() -> None:
    text = METAINFO.read_text() if METAINFO.is_file() else ""
    assert text, "the metainfo does not exist"
    assert "@" not in text
    assert "/home/" not in text


@pytest.mark.skipif(shutil.which("appstreamcli") is None, reason="appstream")
def test_appstream_accepts_the_metainfo() -> None:
    assert METAINFO.is_file()
    result = subprocess.run(
        ["appstreamcli", "validate", "--no-net", str(METAINFO)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(shutil.which("desktop-file-validate") is None, reason="desktop-file-utils")
def test_desktop_file_validate_accepts_the_launcher() -> None:
    result = subprocess.run(
        ["desktop-file-validate", str(DESKTOP)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == "" and result.stderr == ""
