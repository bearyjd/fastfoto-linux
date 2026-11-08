"""The translation tooling: the script, and the CI job that runs it (informational only)."""

import os
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
PINNED_QT = "6.10.3"  # the Qt the committed catalogs were made with


def jobs() -> dict:
    return yaml.safe_load(CI.read_text())["jobs"]


def lupdate() -> str | None:
    return shutil.which("lupdate-qt6") or shutil.which("lupdate")


def can_check_the_catalogs() -> str | None:
    """Why the check cannot run here, None when it can: CI-like (or asked for) and the pinned Qt."""
    tool = lupdate()
    if tool is None:
        return "Qt's lupdate (qt6-linguist) is not installed"
    if not (os.environ.get("CI") or os.environ.get("FASTFOTO_I18N_CHECK") == "1"):
        return "set FASTFOTO_I18N_CHECK=1 (or run in CI) to compare with this machine's lupdate"
    done = subprocess.run([tool, "-version"], capture_output=True, text=True, check=False)
    if PINNED_QT not in done.stdout + done.stderr:
        return f"the committed catalogs were made with Qt {PINNED_QT}; this lupdate differs"
    return None


def test_the_script_refuses_an_unknown_command() -> None:
    result = subprocess.run(
        ["sh", str(SCRIPT), "frobnicate"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 2
    assert "usage" in result.stderr


def test_the_script_compiles_without_unfinished_messages_and_writes_the_pin() -> None:
    text = SCRIPT.read_text()
    assert "-nounfinished" in text
    assert "sha256sum" in text
    assert ".qm.sha256" in text


@pytest.mark.skipif(can_check_the_catalogs() is not None, reason=str(can_check_the_catalogs()))
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
    assert checks[0]["continue-on-error"] is True
    # the whole job, so a failed install or checkout cannot turn it red either
    assert job["continue-on-error"] is True


def test_the_required_gui_job_does_not_depend_on_the_linguist_package() -> None:
    steps = yaml.safe_load(CI.read_text())["jobs"]["gui-fedora"]["steps"]
    assert "linguist" not in " ".join(step.get("run", "") for step in steps)


def test_the_wheel_check_covers_the_compiled_catalog() -> None:
    assert "gui/translations/fastfoto_de\\.qm" in CI.read_text()
