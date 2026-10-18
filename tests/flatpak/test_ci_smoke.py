"""After the bundle is built, the CI job installs it and runs OCR inside its sandbox: the one
proof that what the manifest builds can be found and used by the app (the Python tests use a fake
/app). The steps live in a script so that they can be run by hand on a built bundle."""

import os
import re
from typing import Any

import yaml

from tests.flatpak.helpers import APP_ID, CI, ROOT

SCRIPT = ROOT / "tools" / "ci" / "flatpak-ocr-smoke.sh"
MAX_STEP_MINUTES = 5


def steps() -> list[dict[str, Any]]:
    return yaml.safe_load(CI.read_text())["jobs"]["flatpak"]["steps"]


def index_of(fragment: str) -> int:
    found = [i for i, s in enumerate(steps()) if fragment in str(s.get("uses", s.get("run", "")))]
    assert len(found) == 1, f"expected one CI step with {fragment!r}, found {len(found)}"
    return found[0]


def script() -> str:
    assert SCRIPT.is_file(), f"{SCRIPT.relative_to(ROOT)} does not exist"
    return SCRIPT.read_text(encoding="utf-8")


def test_the_job_installs_the_built_bundle_for_the_user_after_the_build() -> None:
    install = index_of("flatpak install")
    assert install > index_of("flatpak-github-actions/flatpak-builder")
    command = str(steps()[install]["run"])
    assert "--user" in command
    assert "--bundle" in command
    assert f"{APP_ID}.flatpak" in command
    assert "--system" not in command


def test_the_smoke_test_runs_after_the_install_in_a_step_with_a_time_limit() -> None:
    smoke = index_of("tools/ci/flatpak-ocr-smoke.sh")
    assert smoke > index_of("flatpak install")
    assert 0 < steps()[smoke]["timeout-minutes"] <= MAX_STEP_MINUTES


def test_the_script_is_executable_and_stops_at_the_first_failure() -> None:
    assert os.access(SCRIPT, os.X_OK)
    assert script().startswith("#!/bin/sh\n")
    assert re.search(r"^set -eu", script(), re.M)


def test_the_script_checks_tesseract_lists_english_and_orientation_data() -> None:
    text = script()
    assert "--command=tesseract" in text
    assert "--list-langs" in text
    assert re.search(r"grep -(?:q\w*x|x\w*q) eng\b", text)
    assert re.search(r"grep -(?:q\w*x|x\w*q) osd\b", text)


def test_the_script_checks_ocrmypdf_17_runs_as_the_apps_module() -> None:
    text = script()
    assert "-m ocrmypdf --version" in text
    assert re.search(r"grep -q\w* '\^?17\\?\.", text)


def test_the_script_makes_a_pdf_with_the_app_and_finds_the_known_words_in_its_text_layer() -> None:
    text = script()
    assert "--command=ffscan" in text
    assert "doc process" in text
    assert "--ocr on" in text  # exits 3 when the app cannot find its OCR programs
    assert "pdfminer" in text  # bundled with OCRmyPDF; the runtime has no pdftotext
    assert "grep -qi" in text
    assert "searchable" in text


def test_the_script_runs_everything_in_the_sandbox_with_only_one_folder_shared() -> None:
    text = script()
    assert "--filesystem=" in text
    assert "--filesystem=host" not in text
    assert "--filesystem=home" not in text


def test_the_script_installs_nothing_and_removes_only_its_own_folder() -> None:
    text = script()
    for forbidden in ("sudo", "brew", "dnf", "apt", "pip install", "rm -rf", "--system"):
        assert forbidden not in text, forbidden
    assert "mktemp -d" in text


def test_the_script_checks_offline_catalogue_and_actual_sandbox_cache_namespace() -> None:
    text = script()
    assert "--unshare=network --command=python3" in text
    assert "_cache_root(catalog, create=True)" in text
    assert 'Path(os.environ["XDG_DATA_HOME"]).resolve()' in text
    assert "expected / catalog.revision" in text
    assert "tempfile.TemporaryFile(dir=root)" in text
    assert "inventory = discover_languages()" in text
    assert "assert not inventory.error" in text
    assert "0o700" in text
