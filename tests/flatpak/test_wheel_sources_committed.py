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
PURE_PYTHON_TAGS = frozenset({"py3", "py2.py3", "py313"})


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


def accepted(filename: str) -> bool:
    """Whether a wheel runs on CPython 3.13 / x86_64 Linux: pure Python, or cp313 / abi3
    manylinux. (The generator also checks the glibc a manylinux tag needs.)"""
    match = WHEEL_NAME.fullmatch(filename)
    if match is None:
        return False
    python, abi, platform = match["python"], match["abi"], match["platform"]
    if python in PURE_PYTHON_TAGS and abi == "none" and platform == "any":
        return True
    cpython_313 = python == abi == "cp313"
    stable_abi = abi == "abi3" and STABLE_ABI_PYTHON.fullmatch(python) is not None
    tags = platform.split(".")
    linux = any("manylinux" in tag and "x86_64" in tag for tag in tags)
    return (cpython_313 or stable_abi) and linux


def test_every_runtime_wheel_is_cpython_313_manylinux_x86_64_or_pure_python() -> None:
    for source in wheel_sources(load_json(RUNTIME_MODULE)):
        filename = source["url"].rsplit("/", 1)[-1]
        assert accepted(filename), filename
        assert "musllinux" not in filename, filename
        assert re.fullmatch(r"[0-9a-f]{64}", source["sha256"])


@pytest.mark.parametrize(
    "filename",
    [
        "x-1-py3-none-any.whl",
        "x-1-py2.py3-none-any.whl",
        "x-1-py313-none-any.whl",
        "x-1-py312-none-any.whl",
        "x-1-py3-none-manylinux_2_28_x86_64.whl",
        "x-1-cp313-cp313-manylinux_2_28_x86_64.whl",
        "x-1-cp313-cp313-manylinux2014_x86_64.manylinux_2_17_x86_64.whl",
        "x-1-cp312-cp312-manylinux_2_28_x86_64.whl",
        "x-1-cp313-cp313-musllinux_1_2_x86_64.whl",
        "x-1-cp313-cp313-manylinux_2_28_aarch64.whl",
        "x-1-cp39-abi3-manylinux_2_17_x86_64.whl",
        "x-1-cp314-abi3-manylinux_2_17_x86_64.whl",
        "x-1-cp313-cp313-win_amd64.whl",
    ],
)
def test_the_test_accepts_exactly_the_wheels_the_generator_accepts(filename: str) -> None:
    assert accepted(filename) == (generator()._rank(filename) is not None)


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
