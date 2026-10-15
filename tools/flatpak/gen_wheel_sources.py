"""Write the Flatpak modules that install the Python wheels offline.

``runtime`` turns ``uv.lock`` into ``packaging/flatpak/python-deps.json``: the wheels the app runs
on (numpy, opencv-python-headless, pillow), one per package, for CPython 3.13 on manylinux
x86_64. ``build`` does the same for the build backend pinned in ``packaging/requirements-build.txt``
(that one needs the network, to find the files on PyPI). flatpak-builder downloads each wheel and
checks its sha256; pip then installs them with ``--no-index --require-hashes``, so the build never
reaches the network and nothing unpinned can get in.

    python3 tools/flatpak/gen_wheel_sources.py runtime            # rewrite python-deps.json
    python3 tools/flatpak/gen_wheel_sources.py runtime --check    # exit 1 when it is out of date
"""

import argparse
import json
import re
import sys
import tomllib
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
FLATPAK_DIR = ROOT / "packaging" / "flatpak"
RUNTIME_OUTPUT = FLATPAK_DIR / "python-deps.json"
BUILD_OUTPUT = FLATPAK_DIR / "python-build-deps.json"
RUNTIME_REQUIREMENTS = "requirements-desktop.txt"
BUILD_REQUIREMENTS = "requirements-build.txt"
BUILD_TARGET = "${FLATPAK_DEST}/build-backend"
PYPI_RELEASE = "https://pypi.org/pypi/{name}/{version}/json"
PYPI_TIMEOUT_SECONDS = 30
RUNTIME_GLIBC = (2, 42)
PROJECT_SOURCES = ({"editable": "."}, {"virtual": "."})

_WHEEL = re.compile(
    r"(?P<name>[^-]+)-(?P<version>[^-]+)(?:-\d[^-]*)?"
    r"-(?P<python>[^-]+)-(?P<abi>[^-]+)-(?P<platform>[^-]+)\.whl"
)
_MANYLINUX = re.compile(r"manylinux_(?P<major>\d+)_(?P<minor>\d+)_x86_64")
_LEGACY_MANYLINUX = {  # the old names, and the glibc each stands for
    "manylinux1_x86_64": (2, 5),
    "manylinux2010_x86_64": (2, 12),
    "manylinux2014_x86_64": (2, 17),
}
_STABLE_ABI_PYTHON = re.compile(r"cp3(?:[7-9]|1[0-3])")  # abi3 wheels that run on CPython 3.13
_PURE_PYTHON_TAGS = frozenset({"py3", "py2.py3", "py313"})
_PIN = re.compile(r"(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)==(?P<version>\S+)(?P<rest>.*)")
_HASH = re.compile(r"--hash=sha256:([0-9a-f]{64})")

Lookup = Callable[[str, str], Sequence[Mapping[str, str]]]


class WheelSelectionError(Exception):
    """No wheel (or no usable one) for a package."""


@dataclass(frozen=True)
class Wheel:
    name: str
    version: str
    filename: str
    url: str
    sha256: str


def _glibc(platform: str) -> tuple[int, int] | None:
    """The newest glibc a platform tag asks for, or None when it is not manylinux x86_64."""
    found: list[tuple[int, int]] = []
    for tag in platform.split("."):
        modern = _MANYLINUX.fullmatch(tag)
        if modern:
            found.append((int(modern["major"]), int(modern["minor"])))
        elif tag in _LEGACY_MANYLINUX:
            found.append(_LEGACY_MANYLINUX[tag])
    return max(found) if found else None


def _rank(filename: str) -> tuple[int, int] | None:
    """How much a wheel is wanted on CPython 3.13 / x86_64 (higher wins); None: unusable."""
    parts = _WHEEL.fullmatch(filename)
    if parts is None:
        return None
    python, abi, platform = parts["python"], parts["abi"], parts["platform"]
    if python in _PURE_PYTHON_TAGS and abi == "none" and platform == "any":
        return (0, 0)
    interpreter_ok = python == abi == "cp313" or (
        abi == "abi3" and _STABLE_ABI_PYTHON.fullmatch(python) is not None
    )
    return _glibc(platform) if interpreter_ok else None


def _best(name: str, candidates: Sequence[Wheel]) -> Wheel:
    ranked = [(rank, wheel) for wheel in candidates if (rank := _rank(wheel.filename)) is not None]
    if not ranked:
        raise WheelSelectionError(
            f"{name}: no wheel for CPython 3.13 on manylinux x86_64 "
            f"(found {len(candidates)} file(s)); the Flatpak installs wheels only"
        )
    return max(ranked, key=lambda pair: (pair[0], pair[1].filename))[1]


def _locked_wheels(package: Mapping[str, Any]) -> list[Wheel]:
    found = []
    for entry in package.get("wheels", []):
        filename = entry["url"].rsplit("/", 1)[-1]
        sha256 = entry["hash"].removeprefix("sha256:")
        found.append(Wheel(package["name"], package["version"], filename, entry["url"], sha256))
    return found


def _runtime_closure(lock: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """The project's dependencies, and theirs, without its dev group (name order)."""
    packages = {package["name"]: package for package in lock["package"]}
    roots = [p for p in packages.values() if p.get("source") in PROJECT_SOURCES]
    if len(roots) != 1:
        raise WheelSelectionError(f"expected one project package in the lock, found {len(roots)}")
    wanted: dict[str, Mapping[str, Any]] = {}
    pending = [roots[0]]
    while pending:
        for dependency in pending.pop().get("dependencies", []):
            name = dependency["name"]
            if "marker" in dependency:
                raise WheelSelectionError(f"{name} has an environment marker; not supported here")
            if name not in packages:
                raise WheelSelectionError(f"{name} is a dependency but is not in the lock")
            if name not in wanted:
                wanted[name] = packages[name]
                pending.append(packages[name])
    return [wanted[name] for name in sorted(wanted)]


def runtime_wheels(lock: Mapping[str, Any]) -> tuple[Wheel, ...]:
    """One wheel for each package the app needs at run time, in name order."""
    return tuple(_best(p["name"], _locked_wheels(p)) for p in _runtime_closure(lock))


def _wheel_source(wheel: Wheel) -> dict[str, str]:
    return {"type": "file", "url": wheel.url, "sha256": wheel.sha256}


def _module(
    name: str, requirements: str, install_to: str, wheels: Sequence[Wheel]
) -> dict[str, Any]:
    command = (
        'pip3 install --verbose --no-index --find-links="file://${PWD}" --require-hashes '
        f"--no-deps {install_to} -r {requirements}"
    )
    return {
        "name": name,
        "buildsystem": "simple",
        "build-commands": [command],
        "sources": [
            {"type": "file", "path": f"../{requirements}"},
            *(_wheel_source(wheel) for wheel in wheels),
        ],
    }


def runtime_module(lock: Mapping[str, Any]) -> dict[str, Any]:
    """The module that installs the runtime wheels into /app."""
    return _module(
        "python-deps", RUNTIME_REQUIREMENTS, "--prefix=${FLATPAK_DEST}", runtime_wheels(lock)
    )


def _pins(requirements: str) -> list[tuple[str, str, frozenset[str]]]:
    pins = []
    for line in requirements.replace("\\\n", " ").splitlines():
        match = _PIN.match(line.strip())
        if match:
            hashes = frozenset(_HASH.findall(match["rest"]))
            pins.append((match["name"].lower(), match["version"], hashes))
    return sorted(pins)


def build_wheels(requirements: str, lookup: Lookup) -> tuple[Wheel, ...]:
    """The pure-Python wheel of each pin whose hash the requirements list, in name order."""
    chosen = []
    for name, version, hashes in _pins(requirements):
        candidates = [
            Wheel(name, version, found["filename"], found["url"], found["sha256"])
            for found in lookup(name, version)
            if found["filename"].endswith(".whl") and found["sha256"] in hashes
        ]
        pure = [wheel for wheel in candidates if _rank(wheel.filename) == (0, 0)]
        if not pure:
            raise WheelSelectionError(f"{name}=={version}: no pure-Python wheel with a pinned hash")
        chosen.append(_best(name, pure))
    return tuple(chosen)


def build_module(wheels: Sequence[Wheel]) -> dict[str, Any]:
    """The module that installs the build backend apart from /app's Python packages."""
    return _module("python-build-deps", BUILD_REQUIREMENTS, f"--target={BUILD_TARGET}", wheels)


def render(module: Mapping[str, Any]) -> str:
    return json.dumps(module, indent=2) + "\n"


def pypi_files(name: str, version: str) -> list[dict[str, str]]:
    """The files PyPI has for a release: file name, URL and sha256 of each."""
    url = PYPI_RELEASE.format(name=name, version=version)
    with urllib.request.urlopen(url, timeout=PYPI_TIMEOUT_SECONDS) as response:
        release = json.load(response)
    return [
        {"filename": f["filename"], "url": f["url"], "sha256": f["digests"]["sha256"]}
        for f in release["urls"]
    ]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    runtime = commands.add_parser("runtime", help="the wheels in uv.lock")
    runtime.add_argument("--lock", type=Path, default=ROOT / "uv.lock")
    runtime.add_argument("--output", type=Path, default=RUNTIME_OUTPUT)
    build = commands.add_parser("build", help="the build backend (needs the network)")
    build.add_argument("--requirements", type=Path, default=ROOT / "packaging" / BUILD_REQUIREMENTS)
    build.add_argument("--output", type=Path, default=BUILD_OUTPUT)
    for command in (runtime, build):
        command.add_argument(
            "--check", action="store_true", help="change nothing; exit 1 if the file is stale"
        )
    return parser


def _wanted_text(arguments: argparse.Namespace, lookup: Lookup | None) -> str:
    if arguments.command == "runtime":
        return render(runtime_module(tomllib.loads(arguments.lock.read_text(encoding="utf-8"))))
    requirements = arguments.requirements.read_text(encoding="utf-8")
    return render(build_module(build_wheels(requirements, lookup or pypi_files)))


def main(argv: Sequence[str] | None = None, *, lookup: Lookup | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        wanted = _wanted_text(arguments, lookup)
    except (WheelSelectionError, OSError, ValueError, KeyError) as error:
        print(f"gen_wheel_sources: {error}", file=sys.stderr)
        return 1
    output: Path = arguments.output
    if not arguments.check:
        output.write_text(wanted, encoding="utf-8")
        return 0
    if output.is_file() and output.read_text(encoding="utf-8") == wanted:
        return 0
    print(
        f"gen_wheel_sources: {output} is out of date; run: "
        f"python3 tools/flatpak/gen_wheel_sources.py {arguments.command}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
