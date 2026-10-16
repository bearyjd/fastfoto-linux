"""The committed wheel sources are what the generator makes of uv.lock and the build pins."""

import re
import tomllib
from pathlib import Path

import pytest

from tests.flatpak.helpers import (
    BUILD_MODULE,
    FLATPAK_DIR,
    PACKAGING,
    ROOT,
    RUNTIME_MODULE,
    generator,
    load_json,
)

WHEEL_NAME = re.compile(
    r"(?P<name>[^-]+)-(?P<version>[^-]+)-(?P<python>[^-]+)-(?P<abi>[^-]+)-(?P<platform>.+)\.whl"
)
STABLE_ABI_PYTHON = re.compile(r"cp3(?:[7-9]|1[0-3])")  # abi3 wheels that run on CPython 3.13


def pins(path: Path) -> dict[str, tuple[str, set[str]]]:
    """name -> (version, hashes) of a pip requirements file with hashes."""
    found: dict[str, tuple[str, set[str]]] = {}
    text = path.read_text().replace("\\\n", " ")
    for line in text.splitlines():
        match = re.match(r"([A-Za-z0-9._-]+)==(\S+)(.*)", line.strip())
        if match:
            name = match.group(1).lower().replace("_", "-")
            found[name] = (
                match.group(2),
                set(re.findall(r"sha256:([0-9a-f]{64})", match.group(3))),
            )
    return found


def wheel_sources(module: dict) -> list[dict]:
    return [source for source in module["sources"] if "url" in source]


def test_python_deps_json_is_what_the_generator_makes_of_uv_lock() -> None:
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    assert RUNTIME_MODULE.is_file(), "run tools/flatpak/gen_wheel_sources.py runtime"
    expected = generator().render(generator().runtime_module(lock))
    assert RUNTIME_MODULE.read_text() == expected


def test_every_runtime_wheel_hash_is_the_hash_uv_lock_has_for_that_url() -> None:
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    in_lock = {
        wheel["url"]: wheel["hash"].removeprefix("sha256:")
        for package in lock["package"]
        for wheel in package.get("wheels", [])
    }
    sources = wheel_sources(load_json(RUNTIME_MODULE))
    assert sources
    for source in sources:
        assert in_lock.get(source["url"]) == source["sha256"], source["url"]


def test_the_runtime_wheels_are_the_pinned_runtime_dependencies_and_nothing_else() -> None:
    wanted = pins(PACKAGING / "requirements-desktop.txt")
    names = {}
    for source in wheel_sources(load_json(RUNTIME_MODULE)):
        match = WHEEL_NAME.fullmatch(source["url"].rsplit("/", 1)[-1])
        assert match, source["url"]
        names[match["name"].lower().replace("_", "-")] = match["version"]
    assert names == {name: version for name, (version, _) in wanted.items()}
    assert not [n for n in names if re.match(r"(?i)(pyside|shiboken)", n)]
    assert "opencv-python" not in names  # the non-headless wheel would drag in a GUI stack
    assert "opencv-python-headless" in names


def test_every_runtime_wheel_is_cpython_313_manylinux_x86_64_or_pure_python() -> None:
    for source in wheel_sources(load_json(RUNTIME_MODULE)):
        match = WHEEL_NAME.fullmatch(source["url"].rsplit("/", 1)[-1])
        assert match, source["url"]
        if (match["python"], match["abi"], match["platform"]) == ("py3", "none", "any"):
            assert re.fullmatch(r"[0-9a-f]{64}", source["sha256"])
            continue
        cpython_313 = match["python"] == match["abi"] == "cp313"
        stable_abi = match["abi"] == "abi3" and STABLE_ABI_PYTHON.fullmatch(match["python"])
        assert cpython_313 or stable_abi, source["url"]
        assert "manylinux" in match["platform"], source["url"]
        assert "x86_64" in match["platform"], source["url"]
        assert "musllinux" not in match["platform"], source["url"]
        assert re.fullmatch(r"[0-9a-f]{64}", source["sha256"])


def test_each_package_has_exactly_one_runtime_wheel() -> None:
    names = [
        s["url"].rsplit("/", 1)[-1].split("-")[0] for s in wheel_sources(load_json(RUNTIME_MODULE))
    ]
    assert len(names) == len(set(names))


def test_the_runtime_hashes_pip_checks_come_from_the_file_ci_already_ties_to_uv_lock() -> None:
    module = load_json(RUNTIME_MODULE)
    [requirements] = [s for s in module["sources"] if "path" in s]
    assert (FLATPAK_DIR / requirements["path"]).resolve() == PACKAGING / "requirements-desktop.txt"
    # pip's hashes must admit the very wheels flatpak-builder downloads.
    wanted = pins(PACKAGING / "requirements-desktop.txt")
    for source in wheel_sources(module):
        name = source["url"].rsplit("/", 1)[-1].split("-")[0].lower().replace("_", "-")
        assert source["sha256"] in wanted[name][1], name


def test_the_build_backend_wheels_are_the_pins_of_requirements_build_txt() -> None:
    wanted = pins(PACKAGING / "requirements-build.txt")
    assert "hatchling" in wanted
    found = {}
    for source in wheel_sources(load_json(BUILD_MODULE)):
        filename = source["url"].rsplit("/", 1)[-1]
        match = WHEEL_NAME.fullmatch(filename)
        assert match, filename
        assert (match["python"], match["abi"], match["platform"]) in {
            ("py3", "none", "any"),
            ("py2.py3", "none", "any"),
        }, "the build backend must be pure Python"
        name = match["name"].lower().replace("_", "-")
        assert source["sha256"] in wanted[name][1], name
        found[name] = match["version"]
    assert found == {name: version for name, (version, _) in wanted.items()}


def test_the_sources_are_downloaded_from_pypi_over_https() -> None:
    for path in (RUNTIME_MODULE, BUILD_MODULE):
        for source in wheel_sources(load_json(path)):
            assert source["url"].startswith("https://files.pythonhosted.org/packages/"), source


@pytest.mark.parametrize("path", [RUNTIME_MODULE, BUILD_MODULE])
def test_the_generated_files_are_in_the_canonical_form(path: Path) -> None:
    module = load_json(path)
    assert path.read_text() == generator().render(module)
