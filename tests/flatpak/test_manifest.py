"""The Flatpak manifest: what is built, from what, and what the sandbox may do."""

import re
from pathlib import Path
from typing import Any

import pytest

from fastfoto_linux.scanner.target import SHIM_ENV_VAR, SHIM_FILENAME
from tests.flatpak.helpers import (
    APP_ID,
    BUILD_MODULE,
    MANIFEST,
    ROOT,
    RUNTIME_MODULE,
    SHIM_INSTALL_PATH,
    commands,
    load_json,
    load_manifest,
    module,
    modules,
)

SANE_TARBALL_SHA256 = "f99205c903dfe2fb8990f0c531232c9a00ec9c2c66ac7cb0ce50b4af9f407a72"
PLATFORM_BRANCH = "6.11"
GRANTS = {
    "--socket=wayland",
    "--socket=fallback-x11",
    "--share=ipc",
    "--device=dri",
    "--device=all",  # USB: libusb opens /dev/bus/usb/BBB/DDD
    "--share=network",  # the Wi-Fi fallback
    "--filesystem=xdg-pictures",
    f"--env={SHIM_ENV_VAR}={SHIM_INSTALL_PATH}",
}
FORBIDDEN_PREFIXES = (
    "--filesystem=host",
    "--filesystem=home",
    "--filesystem=/",
    "--filesystem=~",
    "--socket=x11",
    "--socket=session-bus",
    "--socket=system-bus",
    "--socket=ssh-auth",
    "--talk-name=",
    "--system-talk-name=",
    "--own-name=",
    "--device=input",
    "--env=SANE_CONFIG_DIR",  # a USB scan removes it; the compiled-in folder is what counts
    "--env=LD_PRELOAD",
    "--allow=devel",
    "--allow=multiarch",
)


def all_sources() -> list[tuple[Path, dict[str, Any]]]:
    return [(base, src) for base, entry in modules() for src in entry.get("sources", [])]


def test_the_application_has_the_reverse_dns_id_and_launches_the_gui() -> None:
    manifest = load_manifest()
    assert manifest["app-id"] == APP_ID
    assert manifest["command"] == "fastfoto"
    assert MANIFEST.name == f"{APP_ID}.yml"


def test_runtime_sdk_and_base_app_are_the_kde_platform_on_one_branch() -> None:
    manifest = load_manifest()
    assert manifest["runtime"] == "org.kde.Platform"
    assert manifest["sdk"] == "org.kde.Sdk"
    assert manifest["base"] == "io.qt.PySide.BaseApp"
    assert manifest["runtime-version"] == manifest["base-version"] == PLATFORM_BRANCH


def test_the_sandbox_gets_the_grants_the_app_needs() -> None:
    assert set(load_manifest()["finish-args"]) >= GRANTS


def test_the_sandbox_gets_nothing_broader() -> None:
    arguments = load_manifest()["finish-args"]
    assert len(arguments) == len(set(arguments))
    assert [a for a in arguments if a.startswith(FORBIDDEN_PREFIXES)] == []
    filesystems = {a for a in arguments if a.startswith("--filesystem=")}
    assert filesystems == {"--filesystem=xdg-pictures"}


def test_the_shim_variable_points_to_where_the_shim_module_installs_the_library() -> None:
    assert SHIM_INSTALL_PATH.rsplit("/", 1)[-1] == SHIM_FILENAME
    steps = commands(module("usb-gap-shim"))
    assert re.search(rf"install\b.*{re.escape(SHIM_INSTALL_PATH)}\s*$", steps, re.MULTILINE), steps


def test_the_shim_is_built_with_gcc_from_the_source_never_taken_as_a_binary() -> None:
    shim = module("usb-gap-shim")
    paths = [source["path"] for source in shim["sources"]]
    assert not [p for p in paths if p.endswith(".so")]
    assert "../../tools/usb-gap-shim/ff680w_usb_gap.c" in paths
    for path in paths:
        assert (MANIFEST.parent / path).resolve().is_file(), path
    assert "gcc" in commands(shim) or "make" in commands(shim)


def test_every_download_is_pinned_by_hash_and_every_local_source_exists() -> None:
    sources = all_sources()
    assert sources
    for base, source in sources:
        if "url" in source:
            assert re.fullmatch(r"[0-9a-f]{64}", source.get("sha256", "")), source
        elif source["type"] == "git":
            raise AssertionError(f"git sources are not pinned by hash: {source}")
        elif "path" in source:
            local = (base / source["path"]).resolve()
            assert local.exists(), source
            assert local.is_relative_to(ROOT), source
        else:
            assert source["type"] == "inline", source


def test_a_folder_source_never_holds_private_scans_or_local_build_state() -> None:
    for base, source in all_sources():
        if source["type"] != "dir":
            continue
        folder = (base / source["path"]).resolve()
        assert folder != ROOT
        for private in ("test-scans", "captures", ".venv", ".git"):
            assert not (folder / private).exists(), (folder, private)


def test_sane_backends_is_the_hashed_1_4_0_tarball_of_the_version_that_works_on_the_host() -> None:
    sane = module("sane-backends")
    [archive] = [s for s in sane["sources"] if s.get("type") == "archive"]
    assert archive["url"].endswith("/sane-backends-1.4.0.tar.gz")
    assert archive["sha256"] == SANE_TARBALL_SHA256


def test_sane_builds_only_epsonds_without_locking_and_installs_under_app() -> None:
    sane = module("sane-backends")
    options = " ".join(sane.get("config-opts", []))
    environment = sane.get("build-options", {}).get("env", {})
    assert environment.get("BACKENDS") == "epsonds" or "BACKENDS=epsonds" in options
    assert "--disable-locking" in options  # /var/lock is not writable in the sandbox
    assert "--with-usb" in options
    assert "--sysconfdir" not in options  # the compiled-in folder is /app/etc/sane.d
    assert "libsane-epsonds.so.1" in commands(sane)  # a missing JPEG library drops it silently


def test_the_compiled_in_sane_config_enables_epsonds_over_usb_only() -> None:
    sane = module("sane-backends")
    inline = {
        s["dest-filename"]: s["contents"] for s in sane["sources"] if s.get("type") == "inline"
    }
    assert inline["dll.conf"].split() == ["epsonds"]
    assert [line for line in inline["epsonds.conf"].splitlines() if line.strip()] == ["usb"]
    steps = commands(sane)
    assert "/app/etc/sane.d/dll.conf" in steps or "${FLATPAK_DEST}/etc/sane.d/dll.conf" in steps
    assert "etc/sane.d/epsonds.conf" in steps


def test_python_comes_from_the_two_generated_modules_before_the_project_is_built() -> None:
    names = [
        entry if isinstance(entry, str) else entry["name"] for entry in load_manifest()["modules"]
    ]
    assert RUNTIME_MODULE.name in names
    assert BUILD_MODULE.name in names
    project = names.index("fastfoto-linux")
    assert names.index(RUNTIME_MODULE.name) < project
    assert names.index(BUILD_MODULE.name) < project


def test_the_project_is_installed_as_a_wheel_without_network_or_dependency_resolution() -> None:
    steps = commands(module("fastfoto-linux"))
    for flag in ("--no-index", "--no-build-isolation", "--no-deps"):
        assert flag in steps
    assert "PYTHONPATH=${FLATPAK_DEST}/build-backend" in steps


def test_the_build_backend_is_installed_apart_and_not_shipped() -> None:
    manifest = load_manifest()
    assert "/build-backend" in manifest["cleanup"]
    assert "--target=${FLATPAK_DEST}/build-backend" in commands(load_json(BUILD_MODULE))


def test_the_base_app_is_trimmed_of_web_engine_and_keeps_the_numpy_pip_installs() -> None:
    manifest = load_manifest()
    assert "/app/cleanup-BaseApp.sh" in manifest["cleanup-commands"]
    environment = manifest["build-options"]["env"]
    assert environment.get("BASEAPP_REMOVE_WEBENGINE")
    assert "BASEAPP_DISABLE_NUMPY" not in environment


def test_the_desktop_file_metainfo_and_icon_are_installed_under_the_app_id() -> None:
    steps = commands(module("fastfoto-linux"))
    for template, target in (
        (f"packaging/{APP_ID}.desktop", f"share/applications/{APP_ID}.desktop"),
        (f"packaging/{APP_ID}.metainfo.xml", f"share/metainfo/{APP_ID}.metainfo.xml"),
        (f"packaging/{APP_ID}.svg", f"share/icons/hicolor/scalable/apps/{APP_ID}.svg"),
    ):
        assert template in steps, template
        assert target in steps, target
        assert (ROOT / template).is_file()


@pytest.mark.parametrize("name", ["sane-backends", "usb-gap-shim", "fastfoto-linux"])
def test_the_modules_are_there(name: str) -> None:
    assert module(name)["sources"]
