"""The Flathub submission copy of the manifest stays in step with the manifest CI builds."""

import json
import re
from pathlib import Path
from typing import Any

import yaml

from tests.flatpak.helpers import APP_ID, FLATPAK_DIR, ROOT, load_manifest

FLATHUB_DIR = FLATPAK_DIR / "flathub"
FLATHUB_MANIFEST = FLATHUB_DIR / f"{APP_ID}.yml"
REPO_URL = "https://github.com/bearyjd/fastfoto-linux.git"
# Modules whose sources differ on purpose: Flathub builds from the tagged release, not a folder.
RELEASE_MODULES = {"usb-gap-shim", "fastfoto-linux"}
PLACEHOLDER = "TODO(release)"
JSON_MODULES = ("python-deps.json", "python-build-deps.json")


def flathub() -> dict[str, Any]:
    assert FLATHUB_MANIFEST.is_file(), f"{FLATHUB_MANIFEST.relative_to(ROOT)} does not exist"
    loaded = yaml.safe_load(FLATHUB_MANIFEST.read_text())
    assert isinstance(loaded, dict)
    return loaded


def resolved(manifest: dict[str, Any], base: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for entry in manifest["modules"]:
        out.append(json.loads((base / entry).read_text()) if isinstance(entry, str) else entry)
    return out


def release_sources(entry: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for s in entry["sources"] if s["type"] == "git"]


def test_top_level_settings_and_sandbox_grants_are_the_same_as_the_ci_manifest() -> None:
    ci, submission = load_manifest(), flathub()
    for key in ci.keys() - {"modules"}:
        assert submission.get(key) == ci[key], f"{key} differs between the two manifests"
    assert submission.keys() == ci.keys()


def test_both_manifests_list_the_same_modules_in_the_same_order() -> None:
    ci = [m if isinstance(m, str) else m["name"] for m in load_manifest()["modules"]]
    submission = [m if isinstance(m, str) else m["name"] for m in flathub()["modules"]]
    assert submission == ci


def test_modules_other_than_the_release_ones_are_identical() -> None:
    ci = resolved(load_manifest(), FLATPAK_DIR)
    submission = resolved(flathub(), FLATHUB_DIR)
    assert [m["name"] for m in ci] == [m["name"] for m in submission]
    for ci_module, submission_module in zip(ci, submission, strict=True):
        if ci_module["name"] in RELEASE_MODULES:
            continue
        a, b = json.loads(json.dumps(ci_module)), json.loads(json.dumps(submission_module))
        for source in (*a.get("sources", []), *b.get("sources", [])):
            if "path" in source:
                source["path"] = Path(source["path"]).name  # the copy sits beside its files
        assert a == b, f"module {a['name']} differs between the two manifests"


def test_the_release_modules_build_the_same_commands_from_the_tagged_git_source() -> None:
    ci = {m["name"]: m for m in resolved(load_manifest(), FLATPAK_DIR)}
    for entry in resolved(flathub(), FLATHUB_DIR):
        if entry["name"] not in RELEASE_MODULES:
            continue
        assert entry["buildsystem"] == ci[entry["name"]]["buildsystem"]
        [source] = release_sources(entry)
        assert source["url"] == REPO_URL
        assert not [s for s in entry["sources"] if s["type"] in ("dir", "file", "archive")]


def test_the_tag_and_commit_are_marked_placeholders_or_a_real_pair_never_a_made_up_hash() -> None:
    text = FLATHUB_MANIFEST.read_text()
    for entry in resolved(flathub(), FLATHUB_DIR):
        if entry["name"] not in RELEASE_MODULES:
            continue
        [source] = release_sources(entry)
        assert re.fullmatch(r"v\d+\.\d+\.\d+", source["tag"])
        commit = str(source["commit"])
        assert commit == PLACEHOLDER or re.fullmatch(r"[0-9a-f]{40}", commit)
        assert not re.fullmatch(r"([0-9a-f])\1{39}", commit), "a made up hash"
    assert text.count(PLACEHOLDER) >= 1


def test_the_two_release_modules_use_the_same_tag_and_commit() -> None:
    pairs = {
        (s["tag"], s["commit"])
        for e in resolved(flathub(), FLATHUB_DIR)
        if e["name"] in RELEASE_MODULES
        for s in release_sources(e)
    }
    assert len(pairs) == 1


def test_the_release_source_can_be_updated_by_the_flathub_bot() -> None:
    for entry in resolved(flathub(), FLATHUB_DIR):
        if entry["name"] in RELEASE_MODULES:
            [source] = release_sources(entry)
            assert source["x-checker-data"]["type"] == "git"
            assert "tag-pattern" in source["x-checker-data"]


def test_the_submission_root_holds_every_file_the_manifest_refers_to() -> None:
    for entry in resolved(flathub(), FLATHUB_DIR):
        for source in entry.get("sources", []):
            if "path" in source:
                assert (FLATHUB_DIR / source["path"]).is_file(), source["path"]
                assert ".." not in Path(source["path"]).parts


def test_the_copied_requirements_are_byte_identical_to_the_ones_the_app_installs() -> None:
    for name in ("requirements-ocr.txt", "requirements-build.txt"):
        assert (FLATHUB_DIR / name).read_bytes() == (ROOT / "packaging" / name).read_bytes()


def test_flathub_is_told_the_app_is_built_for_x86_64_only() -> None:
    config = json.loads((FLATHUB_DIR / "flathub.json").read_text())
    assert config == {"only-arches": ["x86_64"]}


def test_the_json_modules_are_listed_by_name_in_the_submission_manifest() -> None:
    assert [m for m in flathub()["modules"] if isinstance(m, str)] == list(JSON_MODULES)
