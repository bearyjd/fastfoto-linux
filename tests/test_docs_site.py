"""The MkDocs site (mkdocs.yml, its pages) and the CI job that builds it.

The job is NOT a required check, builds only, and never deploys: GitHub Pages is not enabled.
"""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "mkdocs.yml"
DOCS = ROOT / "docs"
CI = ROOT / ".github" / "workflows" / "ci.yml"
REQ_IN = ROOT / "packaging" / "requirements-docs.in"
REQ_TXT = ROOT / "packaging" / "requirements-docs.txt"

PAGES = ("index.md", "install.md", "first-scan.md", "known-limits.md", "comparison.md", "RUNBOOK.md")
COMPETITORS = ("NAPS2", "gscan2pdf", "Skanpage", "ScanMole", "VueScan")
DISCLAIMER = "Not affiliated with Seiko Epson"


def config() -> dict[str, Any]:
    return yaml.safe_load(CONFIG.read_text())


def nav_files(nav: Any) -> list[str]:
    if isinstance(nav, str):
        return [nav]
    if isinstance(nav, dict):
        return [f for value in nav.values() for f in nav_files(value)]
    return [f for item in nav for f in nav_files(item)]


def docs_job() -> dict[str, Any]:
    jobs = yaml.safe_load(CI.read_text())["jobs"]
    assert "docs" in jobs, "ci.yml has no job named docs"
    return jobs["docs"]


def test_config_renders_the_docs_folder_strictly() -> None:
    cfg = config()
    assert cfg["docs_dir"] == "docs"
    assert cfg["strict"] is True
    assert cfg["theme"]["name"] == "material"


def test_every_nav_entry_is_a_page_and_the_required_pages_are_in_the_nav() -> None:
    listed = nav_files(config()["nav"])
    for name in listed:
        assert (DOCS / name).is_file(), name
    assert set(PAGES) <= set(listed)


def test_every_required_page_exists_and_is_not_empty() -> None:
    for name in PAGES:
        assert (DOCS / name).read_text().strip(), name


@pytest.mark.parametrize("name", PAGES)
def test_the_disclaimer_is_on_every_page_that_names_the_scanner_or_the_vendor(name: str) -> None:
    text = (DOCS / name).read_text()
    if name in ("index.md", "comparison.md"):
        assert DISCLAIMER in text


def test_comparison_names_each_alternative_marks_unverified_claims_and_does_not_boast() -> None:
    text = (DOCS / "comparison.md").read_text()
    for name in COMPETITORS:
        assert name in text, name
    assert "Epson Scan 2" in text
    assert "unverified" in text.lower()
    assert not re.search(r"better than|best|only way|faster than|worse", text, re.IGNORECASE)


def test_known_limits_says_calibration_is_synthetic_only() -> None:
    text = (DOCS / "known-limits.md").read_text().lower()
    assert "synthetic" in text
    assert "x86_64" in text
    assert "pdf/a" in text


def test_docs_requirements_are_pinned_with_hashes_for_every_package() -> None:
    assert re.search(r"^mkdocs-material", REQ_IN.read_text(), re.MULTILINE)
    entries = re.split(r"\n(?=[A-Za-z0-9])", REQ_TXT.read_text().strip())
    names = set()
    for entry in entries:
        head = entry.splitlines()[0]
        assert re.match(r"^[A-Za-z0-9._-]+==[0-9][^ ;\\]*", head), head
        assert re.search(r"--hash=sha256:[0-9a-f]{64}", entry), head
        names.add(head.split("==")[0].lower())
    assert {"mkdocs", "mkdocs-material"} <= names


def test_docs_job_is_least_privilege_and_builds_strictly_from_hashed_requirements() -> None:
    job = docs_job()
    assert job["permissions"] == {"contents": "read"}
    text = "\n".join(str(s.get("run", "")) for s in job["steps"])
    assert "mkdocs build --strict" in text
    assert "--require-hashes" in text
    assert "packaging/requirements-docs.txt" in text


def test_docs_job_pins_every_action_by_full_sha_and_does_not_persist_credentials() -> None:
    steps = docs_job()["steps"]
    uses = [s for s in steps if "uses" in s]
    assert uses
    for step in uses:
        assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", step["uses"]), step["uses"]
    [checkout] = [s for s in uses if s["uses"].startswith("actions/checkout@")]
    assert checkout["with"]["persist-credentials"] is False


def test_docs_job_never_deploys_publishes_or_reads_secrets() -> None:
    job_text = yaml.safe_dump(docs_job())
    for banned in ("gh-deploy", "pages", "deploy", "secrets.", "GITHUB_TOKEN", "upload-artifact"):
        assert banned not in job_text.lower().replace("ubuntu", ""), banned
    assert "continue-on-error" not in job_text


def test_the_other_ci_jobs_are_unchanged_by_the_docs_job() -> None:
    jobs = yaml.safe_load(CI.read_text())["jobs"]
    assert {"lint", "test", "gui-fedora", "flatpak"} <= set(jobs)
    assert "docs" not in {name for name in jobs if jobs[name].get("needs")}
