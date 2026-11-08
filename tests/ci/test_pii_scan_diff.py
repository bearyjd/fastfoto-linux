"""tools/ci/pii_scan_diff.sh, run on a throwaway git repository."""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "ci" / "pii_scan_diff.sh"
# Built from parts so that this file holds no forbidden text itself.
LAN = "192." + "168.1.20"
HOME = "/home/" + "user/Pictures"
SECRET = "SERIAL" + "-12345"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _scan(repo: Path, extra: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "FASTFOTO_PII_EXTRA_FILE"}
    if extra is not None:
        env["FASTFOTO_PII_EXTRA_FILE"] = str(extra)
    return subprocess.run(
        ["sh", str(SCRIPT), "base"], cwd=repo, env=env, capture_output=True, text=True, check=False
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "a.txt").write_text(f"{LAN} already here\n")
    _git(tmp_path, "add", "a.txt")
    _git(tmp_path, "commit", "-q", "-m", "base")
    _git(tmp_path, "tag", "base")
    return tmp_path


def _commit(repo: Path, text: str) -> None:
    (repo / "b.txt").write_text(text)
    _git(repo, "add", "b.txt")
    _git(repo, "commit", "-q", "-m", "change")


def test_clean_diff_passes_and_old_lines_are_ignored(repo: Path) -> None:
    _commit(repo, "nothing private\n")
    result = _scan(repo)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("text", [f"ip {LAN}\n", f"path {HOME}\n"])
def test_added_private_text_fails(repo: Path, text: str) -> None:
    _commit(repo, text)
    result = _scan(repo)
    assert result.returncode == 1
    assert "b.txt" not in result.stdout


def test_extra_patterns_come_from_the_named_file(repo: Path, tmp_path_factory) -> None:
    extra = tmp_path_factory.mktemp("extra") / "patterns"
    extra.write_text(f"\n{SECRET}\n")
    _commit(repo, f"unit {SECRET}\n")
    assert _scan(repo).returncode == 0
    assert _scan(repo, extra).returncode == 1


def test_unreadable_extra_file_is_an_error(repo: Path, tmp_path_factory) -> None:
    _commit(repo, "fine\n")
    assert _scan(repo, tmp_path_factory.mktemp("x") / "missing").returncode == 66


def test_requires_one_argument(repo: Path) -> None:
    result = subprocess.run(["sh", str(SCRIPT)], cwd=repo, capture_output=True, check=False)
    assert result.returncode == 64
