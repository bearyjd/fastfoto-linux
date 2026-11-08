"""The translation tooling: the script, and the CI job that runs it (informational only)."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "i18n.sh"
CI = ROOT / ".github" / "workflows" / "ci.yml"
PINNED_ACTION = re.compile(r"^actions/checkout@[0-9a-f]{40}$")


def jobs() -> dict:
    return yaml.safe_load(CI.read_text())["jobs"]


def has_lupdate() -> bool:
    return bool(shutil.which("lupdate-qt6") or shutil.which("lupdate"))


def test_the_script_refuses_an_unknown_command() -> None:
    result = subprocess.run(
        ["sh", str(SCRIPT), "frobnicate"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 2
    assert "usage" in result.stderr


@pytest.mark.skipif(not has_lupdate(), reason="Qt's lupdate (qt6-linguist) is not installed")
def test_the_committed_ts_files_match_the_messages_in_the_source() -> None:
    result = subprocess.run(
        ["sh", str(SCRIPT), "check"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_ci_job_is_informational_and_pinned() -> None:
    job = jobs()["i18n"]
    assert re.search(r"^fedora:44@sha256:[0-9a-f]{64}$", job["container"])
    uses = [step["uses"].split(" ")[0] for step in job["steps"] if "uses" in step]
    assert uses
    assert all(PINNED_ACTION.match(name) for name in uses)
    checks = [step for step in job["steps"] if "tools/i18n.sh check" in step.get("run", "")]
    assert len(checks) == 1
    assert checks[0]["continue-on-error"] is True  # the job is green whatever the check says
    assert "continue-on-error" not in job or job["continue-on-error"] is not False


def test_the_required_gui_job_does_not_depend_on_the_linguist_package() -> None:
    steps = yaml.safe_load(CI.read_text())["jobs"]["gui-fedora"]["steps"]
    assert "linguist" not in " ".join(step.get("run", "") for step in steps)


def test_the_wheel_check_covers_the_compiled_catalog() -> None:
    assert "gui/translations/fastfoto_de\\.qm" in CI.read_text()
