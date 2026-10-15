"""The CI job that builds the Flatpak bundle (not a required check; that is a repo setting)."""

import re
from typing import Any

import yaml

from tests.flatpak.helpers import APP_ID, CI, MANIFEST, ROOT, load_manifest

ACTION = "flatpak/flatpak-github-actions/flatpak-builder"
IMAGE = "ghcr.io/flathub-infra/flatpak-github-actions"


def job() -> dict[str, Any]:
    jobs = yaml.safe_load(CI.read_text())["jobs"]
    assert "flatpak" in jobs, "ci.yml has no job named flatpak"
    return jobs["flatpak"]


def test_the_action_is_pinned_by_full_commit_sha_with_its_version_in_a_comment() -> None:
    assert re.search(rf"uses: {re.escape(ACTION)}@[0-9a-f]{{40}} # v\d+\.\d+", CI.read_text())


def test_the_container_image_is_pinned_by_digest_with_its_tag_in_a_comment() -> None:
    text = CI.read_text()
    assert re.search(rf"image: {re.escape(IMAGE)}:kde-\d+\.\d+@sha256:[0-9a-f]{{64}}", text)
    assert re.search(rf"#.*{re.escape(IMAGE)}:kde-\d+\.\d+", text)


def test_the_image_is_the_one_for_the_manifests_kde_branch() -> None:
    image = job()["container"]["image"]
    assert image.startswith(f"{IMAGE}:kde-{load_manifest()['runtime-version']}@sha256:")


def test_the_job_builds_this_manifest_and_uploads_the_bundle() -> None:
    [step] = [s for s in job()["steps"] if str(s.get("uses", "")).startswith(ACTION)]
    arguments = step["with"]
    assert arguments["manifest-path"] == str(MANIFEST.relative_to(ROOT))
    assert arguments["bundle"] == f"{APP_ID}.flatpak"
    assert str(arguments.get("upload-artifact", "true")).lower() == "true"


def test_the_container_may_use_the_sandbox_it_needs_and_the_job_has_a_time_limit() -> None:
    assert "--privileged" in job()["container"]["options"]
    assert job()["timeout-minutes"] >= 30
