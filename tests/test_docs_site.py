"""The MkDocs site (mkdocs.yml, its pages) and the CI job that builds it.

The job is NOT a required check, builds only, and never deploys: GitHub Pages is not enabled.
"""

import importlib.util
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "mkdocs.yml"
DOCS = ROOT / "docs"
CI = ROOT / ".github" / "workflows" / "ci.yml"
CHECKER = ROOT / "tools" / "ci" / "docs_site_offline.py"
REQ_IN = ROOT / "packaging" / "requirements-docs.in"
REQ_TXT = ROOT / "packaging" / "requirements-docs.txt"

PAGES = (
    "index.md",
    "install.md",
    "first-scan.md",
    "known-limits.md",
    "comparison.md",
    "RUNBOOK.md",
)
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


@pytest.mark.parametrize("name", ("index.md", "comparison.md"))
def test_the_affiliation_disclaimer_is_on_the_home_and_comparison_pages(name: str) -> None:
    assert DISCLAIMER in (DOCS / name).read_text()


def test_comparison_names_each_alternative_marks_unverified_claims_and_does_not_boast() -> None:
    text = (DOCS / "comparison.md").read_text()
    for name in COMPETITORS:
        assert name in text, name
    assert "Epson Scan 2" in text
    assert "unverified" in text.lower()
    prose = re.sub(r"<https?://[^>]*>", "", text)
    assert not re.search(r"better than|\bbest\b|only way|faster than|worse", prose, re.IGNORECASE)


def known_limits() -> str:
    return " ".join((DOCS / "known-limits.md").read_text().lower().split())


@pytest.mark.parametrize(
    "phrase",
    [
        "synthetic",
        "x86_64",
        "pdf/a",
        "only 8-bit rgb png",
        "animated",
        "no output size cap",
        "about 100 mb",
        "small",
        "sharpening amount is uncalibrated",
        "scanner_capabilities.md",
        "design/photo-geometry.md",
    ],
)
def test_known_limits_states_each_limit(phrase: str) -> None:
    assert phrase in known_limits()


def test_known_limits_links_the_deskew_design_note_and_the_capability_inventory() -> None:
    text = (DOCS / "known-limits.md").read_text()
    assert "](SCANNER_CAPABILITIES.md)" in text
    assert re.search(
        r"\]\(https://github\.com/[^)]*docs/design/(documents|photo-geometry)\.md", text
    )


def test_flatpak_device_access_is_described_as_all_device_nodes_including_the_gpu() -> None:
    text = " ".join((DOCS / "install.md").read_text().split())
    assert "--device=all" in text
    assert "every device node of the host" in text
    assert "GPU" in text


def test_cli_document_scan_is_not_promised_a_review() -> None:
    text = " ".join((DOCS / "first-scan.md").read_text().split())
    assert "The document flow is review-first" not in text
    assert "writes the PDF directly" in text
    assert "desktop app" in text.split("writes the PDF directly")[1]


def test_comparison_marks_the_fastfoto_app_row_unverified() -> None:
    [row] = [
        x for x in (DOCS / "comparison.md").read_text().splitlines() if "Epson FastFoto (" in x
    ]
    assert row.rstrip().endswith("| unverified |")


def test_pages_say_offline_by_default_not_fully_offline() -> None:
    for name in ("index.md", "comparison.md"):
        text = (DOCS / name).read_text().lower()
        assert "offline by default" in text, name
        assert "fully offline" not in text, name


def test_the_ci_warning_silencer_carries_the_material_end_of_life_date_and_a_todo() -> None:
    lines = CI.read_text().splitlines()
    [i] = [n for n, line in enumerate(lines) if "NO_MKDOCS_2_WARNING" in line]
    nearby = "\n".join(lines[max(0, i - 4) : i + 1])
    assert "2027-05-05" in nearby
    assert "TODO" in nearby


def test_docs_requirements_were_locked_with_a_cutoff_a_week_before_the_build() -> None:
    m = re.search(r"exclude-newer[:= ]+(\d{4}-\d{2}-\d{2})", REQ_IN.read_text())
    assert m, "requirements-docs.in must record the --exclude-newer date it was locked with"
    assert m.group(1) <= "2026-10-31"


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
    job_text = yaml.safe_dump(docs_job()).lower()
    for banned in ("gh-deploy", "pages", "deploy", "secrets.", "github_token", "upload-artifact"):
        assert banned not in job_text.replace("ubuntu", ""), banned
    assert "continue-on-error" not in job_text


def test_no_job_needs_docs_and_docs_needs_nothing() -> None:
    jobs = yaml.safe_load(CI.read_text())["jobs"]
    assert {"lint", "test", "gui-fedora", "flatpak"} <= set(jobs)
    assert "needs" not in jobs["docs"]
    for name, job in jobs.items():
        needs = job.get("needs", [])
        needs = [needs] if isinstance(needs, str) else needs
        assert "docs" not in needs, name


def test_the_build_makes_no_request_to_a_third_party_by_default() -> None:
    cfg = config()
    assert cfg["theme"]["font"] is False
    for key in ("repo_url", "repo_name", "extra_javascript", "extra_css"):
        assert key not in cfg, key
    extra = cfg.get("extra", {})
    assert "analytics" not in extra
    assert extra.get("generator") is False
    assert not any(k in cfg["theme"] for k in ("custom_dir", "logo", "favicon"))


def test_the_ci_job_checks_the_built_site_for_external_assets() -> None:
    text = "\n".join(str(s.get("run", "")) for s in docs_job()["steps"])
    assert "tools/ci/docs_site_offline.py" in text


def load_checker() -> Any:
    spec = importlib.util.spec_from_file_location("docs_site_offline", CHECKER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "html",
    [
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css?family=Roboto">',
        '<link rel="preconnect" href="https://fonts.gstatic.com/" crossorigin>',
        '<script src="https://cdn.jsdelivr.net/x.js"></script>',
        '<script src="//unpkg.com/x.js"></script>',
        '<img src="http://example.com/a.png">',
        '<style>@import url("https://fonts.googleapis.com/x");</style>',
        '<div style="background:url(https://example.com/a.png)"></div>',
        '<iframe src="https://example.com"></iframe>',
        '<link rel="icon" href="https://example.com/i.png">',
    ],
)
def test_the_checker_flags_every_kind_of_external_load(html: str) -> None:
    assert load_checker().external_references(html)


@pytest.mark.parametrize(
    "html",
    [
        '<a href="https://example.com/page">a plain link</a>',
        '<link rel="stylesheet" href="assets/css/main.css">',
        '<script src="../assets/js/bundle.js"></script>',
        '<img src="data:image/png;base64,AAAA">',
        "<p>https://example.com is text, not a load</p>",
    ],
)
def test_the_checker_allows_plain_links_and_local_assets(html: str) -> None:
    assert load_checker().external_references(html) == []
