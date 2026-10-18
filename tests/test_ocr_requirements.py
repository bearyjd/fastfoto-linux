"""The ``ocr`` extra: ocrmypdf is optional for a source install, and the native installer gets it
from its own hashed file, which is what uv.lock says. The Flatpak installs that same file, which
holds the desktop's pins as well, so it gets OCR too."""

import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "packaging" / "requirements-desktop.txt"
OCR = ROOT / "packaging" / "requirements-ocr.txt"
CI = ROOT / ".github" / "workflows" / "ci.yml"
PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==(\S+)", re.M)


def pins(path: Path) -> dict[str, str]:
    return dict(PIN.findall(path.read_text(encoding="utf-8")))


def project() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]


def test_ocrmypdf_is_the_optional_ocr_extra_and_not_a_plain_dependency() -> None:
    extras = project()["optional-dependencies"]
    assert [name for name in extras] == ["ocr"]
    assert [re.split(r"[<>=!~ ]", spec)[0] for spec in extras["ocr"]] == ["ocrmypdf"]
    assert not [spec for spec in project()["dependencies"] if "ocrmypdf" in spec.lower()]


def test_the_ocr_requirements_are_what_the_lock_file_says() -> None:
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is not installed")
    command = [uv, "export", "--locked", "--no-dev", "--no-emit-project", "--extra", "ocr"]
    exported = subprocess.run(
        [*command, "--hashes", "--no-annotate", "--no-header", "--quiet"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert exported.returncode == 0, exported.stderr
    shipped = OCR.read_text(encoding="utf-8")
    assert "--hash=sha256:" in shipped
    assert shipped == exported.stdout


def test_the_ocr_requirements_pin_ocrmypdf_and_every_desktop_pin_the_same_way() -> None:
    ocr, desktop = pins(OCR), pins(DESKTOP)
    assert "ocrmypdf" in ocr
    assert desktop.items() <= ocr.items()


def test_the_desktop_requirements_stay_free_of_ocr_because_the_ocr_file_adds_it() -> None:
    assert "ocrmypdf" not in pins(DESKTOP)


def test_ci_checks_the_ocr_requirements_against_the_lock_file() -> None:
    text = CI.read_text(encoding="utf-8")
    [step] = [line for line in text.splitlines() if "requirements-ocr.txt" in line]
    assert "uv export --locked" in step
    assert "--extra ocr" in step
    assert "diff - packaging/requirements-ocr.txt" in step
