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


def problems(tmp_path: Path, files: dict[str, str]) -> list[str]:
    for name, text in files.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return load_checker().check_site(tmp_path)


EVIL = "https://evil.example/x"
TAB = "\t"

MUST_FAIL = {
    "script src": {"index.html": f'<script src="{EVIL}.js"></script>'},
    "fetch in a js file": {"js/app.js": f'fetch("{EVIL}")'},
    "inline script fetch": {"index.html": f'<script>fetch("{EVIL}")</script>'},
    "srcset second candidate": {"index.html": f'<img srcset="a.png 1x, {EVIL}.png 2x">'},
    "canonical stylesheet": {"index.html": f'<link rel="canonical stylesheet" href="{EVIL}.css">'},
    "meta refresh": {"index.html": f'<meta http-equiv="refresh" content="0;url={EVIL}">'},
    "meta refresh protocol relative": {
        "index.html": '<meta http-equiv=refresh content="0;url=//evil.example/">'
    },
    "iframe srcdoc": {"index.html": f'<iframe srcdoc="<img src={EVIL}>"></iframe>'},
    "iframe data html": {"index.html": '<iframe src="data:text/html,<p>x</p>"></iframe>'},
    "inline svg xlink": {"index.html": f'<svg><use xlink:href="{EVIL}.svg#a"/></svg>'},
    "object data": {"index.html": f'<object data="{EVIL}.svg"></object>'},
    "svg file image": {
        "a.svg": f'<svg xmlns="http://www.w3.org/2000/svg"><image href="{EVIL}.png"/></svg>'
    },
    "css escape": {"css/a.css": "a{background:url(\\68 ttps://evil.example/a.png)}"},
    "css import comment": {"css/a.css": '@import/**/"https://evil.example/a.css";'},
    "css url in string": {"css/a.css": 'a::after{content:"url(https://evil.example/a.png)"}'},
    "css protocol relative": {"css/a.css": "a{background:url(//evil.example/a.png)}"},
    "tab in scheme": {"index.html": '<img src="ht&#9;tps://evil.example/a.png">'},
    "named colon": {"index.html": '<img src="https&colon;//evil.example/a.png">'},
    "hex slashes": {"index.html": '<img src="&#x2f;&#x2f;evil.example/a.png">'},
    "base with tab": {"index.html": f'<base href="ht{TAB}tps://evil.example/">'},
    "duplicate src": {"index.html": '<img src="a.png" src="b.png">'},
    "duplicate src external second": {"index.html": f'<img src="a.png" src="{EVIL}">'},
    "javascript url": {"index.html": '<a href="javascript:alert(1)">x</a>'},
    "javascript url with tab": {"index.html": '<a href="java&#9;script:alert(1)">x</a>'},
    "data html in img": {"index.html": '<img src="data:text/html;base64,AAAA">'},
    "form action": {"index.html": f'<form action="{EVIL}"></form>'},
    "protocol relative script": {"index.html": "<script src=//evil.example/x.js></script>"},
    "comment": {"index.html": f"<!-- {EVIL} -->"},
    "look-alike namespace": {"a.svg": '<svg xmlns="http://www.w3.org/2000/svg.evil.example/"/>'},
    "unlisted vendor host": {"assets/javascripts/b.js": "//" + " see https://evil.example/x"},
    "weird file type": {"x.webmanifest": f'{{"icons":[{{"src":"{EVIL}"}}]}}'},
}

MUST_PASS = {
    "relative everything": {
        "index.html": '<a href="a/">a</a><img src="i.png" srcset="i.png 1x, j.png 2x">'
        '<link rel="stylesheet" href="assets/c.css"><script src="../b.js"></script>'
        '<base href="/docs/">',
        "css/a.css": "@import 'b.css'; a{background:url(i.png)}",
        "js/app.js": 'fetch("data.json")',
    },
    "external anchor": {
        "index.html": '<a href="https://example.com/page">x</a><a href="//example.com/">y</a>'
    },
    "namespaces": {
        "index.html": '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
        '<math xmlns="http://www.w3.org/1998/Math/MathML"></math></svg>',
        "sitemap.xml": '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>',
    },
    "css comment": {"css/a.css": "/* see https://example.com/license */ a{color:red}"},
    "image data urls": {
        "index.html": '<img src="data:image/png;base64,AAAA">',
        "css/a.css": 'a{background:url("data:image/svg+xml;charset=utf-8,%3Csvg%3E")}',
    },
    "prose text and code": {"index.html": "<p>See https://example.com and <code>//x</code></p>"},
    "css pseudo classes": {"css/a.css": "a:hover{color:red}b::after{content:'x'}"},
    "allowed vendor host in a comment": {"assets/javascripts/b.js": "/* https://github.com/x */"},
    "search index is data": {"search/search_index.json": f'{{"text":"{EVIL}"}}'},
    "binary files": {"assets/i.png": "\x89PNG https://evil.example/"},
}


@pytest.mark.parametrize("name", MUST_FAIL)
def test_the_checker_fails_every_way_to_load_from_elsewhere(name: str, tmp_path: Path) -> None:
    assert problems(tmp_path, MUST_FAIL[name])


@pytest.mark.parametrize("name", MUST_PASS)
def test_the_checker_allows_local_assets_plain_links_and_namespaces(
    name: str, tmp_path: Path
) -> None:
    assert problems(tmp_path, MUST_PASS[name]) == []


def test_the_checker_names_the_file_and_the_string(tmp_path: Path) -> None:
    [found] = problems(tmp_path, {"js/app.js": f'fetch("{EVIL}")'})
    assert "js/app.js" in found
    assert "evil.example" in found


def test_the_theme_assets_are_not_excluded_from_the_build() -> None:
    # exclude_docs also drops the theme's own assets/ folder, which would leave pages unstyled.
    lines = [line.strip() for line in config()["exclude_docs"].splitlines()]
    assert not [x for x in lines if x.strip("/") == "assets"]


def squashed(name: str) -> str:
    return " ".join((DOCS / name).read_text().split())


def test_native_install_lists_the_sane_prerequisite() -> None:
    text = squashed("install.md")
    assert "scanimage" in text
    assert "epsonds" in text
    assert text.index("scanimage") < text.index("tools/install-desktop.sh")


def test_flatpak_only_users_get_the_ffscan_command_through_flatpak_run() -> None:
    text = squashed("first-scan.md")
    assert "flatpak run --command=ffscan io.github.bearyjd.FastFotoLinux devices" in text


def test_wifi_scanning_uses_net_and_devices_is_not_a_reachability_test() -> None:
    text = squashed("first-scan.md")
    assert "--net HOST" in text
    assert "ffscan devices --net HOST" in text
    assert "does not contact" in text
    assert "USB" in text.split("ffscan devices")[1]
