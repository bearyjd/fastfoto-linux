"""Write the Flatpak modules that install the Python wheels offline.

``runtime`` turns ``uv.lock`` into ``packaging/flatpak/python-deps.json``: the wheels the app runs
on (numpy, opencv-python-headless, pillow, and OCRmyPDF from the ``ocr`` extra, with theirs), one
per package, for CPython 3.13 on manylinux x86_64. A dependency that has an environment marker is
followed when the marker holds in that environment and left out when it does not. ``build`` does
the same for the build backend pinned in ``packaging/requirements-build.txt`` (that one needs the
network, to find the files on PyPI). flatpak-builder downloads each wheel and checks its sha256;
pip then installs them with ``--no-index --require-hashes``, so the build never reaches the
network and nothing unpinned can get in.

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
# The file pip installs from: the desktop's pins and the ``ocr`` extra's, hashed, from uv.lock.
RUNTIME_REQUIREMENTS = "requirements-ocr.txt"
RUNTIME_EXTRAS = ("ocr",)  # the optional dependencies of the project that the Flatpak brings
BUILD_REQUIREMENTS = "requirements-build.txt"
BUILD_TARGET = "${FLATPAK_DEST}/build-backend"
PYPI_RELEASE = "https://pypi.org/pypi/{name}/{version}/json"
PYPI_TIMEOUT_SECONDS = 30
# The glibc of the runtime the app runs on; a wheel that needs a newer one would install and then
# fail to load. Check it with: flatpak run --command=ldd org.kde.Platform//6.11 --version
# (change it together with `runtime-version` in the manifest).
RUNTIME_GLIBC = (2, 42)
PROJECT_SOURCES = ({"editable": "."}, {"virtual": "."})
# What the Flatpak's Python is, for the environment markers of the dependencies.
FLATPAK_ENVIRONMENT = {
    "implementation_name": "cpython",
    "os_name": "posix",
    "platform_machine": "x86_64",
    "platform_python_implementation": "CPython",
    "platform_system": "Linux",
    "sys_platform": "linux",
}

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
_MARKER_TEST = re.compile(r"(?P<variable>[a-z_]+) (?P<operator>==|!=) '(?P<value>[^']*)'")
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
    """The newest glibc the runtime can offer a wheel's platform tags, or None when none fits.

    A wheel can carry several tags (``manylinux_2_27_x86_64.manylinux_2_28_x86_64``) and runs where
    any one of them does, so a tag above ``RUNTIME_GLIBC`` is dropped, not the whole wheel.
    """
    found: list[tuple[int, int]] = []
    for tag in platform.split("."):
        modern = _MANYLINUX.fullmatch(tag)
        if modern:
            found.append((int(modern["major"]), int(modern["minor"])))
        elif tag in _LEGACY_MANYLINUX:
            found.append(_LEGACY_MANYLINUX[tag])
    fitting = [glibc for glibc in found if glibc <= RUNTIME_GLIBC]
    return max(fitting) if fitting else None


def _rank(filename: str) -> tuple[int, int] | None:
    """How much a wheel is wanted on CPython 3.13 / x86_64 (higher wins); None: unusable."""
    parts = _WHEEL.fullmatch(filename)
    if parts is None:
        return None
    python, abi, platform = parts["python"], parts["abi"], parts["platform"]
    if python in _PURE_PYTHON_TAGS and abi == "none" and platform == "any":
        return (0, 0)
    interpreter_ok = (
        python == abi == "cp313"
        or (abi == "abi3" and _STABLE_ABI_PYTHON.fullmatch(python) is not None)
        or (python in _PURE_PYTHON_TAGS and abi == "none")  # a ctypes binding, like pypdfium2
    )
    return _glibc(platform) if interpreter_ok else None


def _best(name: str, candidates: Sequence[Wheel]) -> Wheel:
    ranked = [(rank, wheel) for wheel in candidates if (rank := _rank(wheel.filename)) is not None]
    if not ranked:
        raise WheelSelectionError(
            f"{name}: no wheel for CPython 3.13 on manylinux x86_64 that runs on glibc "
            f"{RUNTIME_GLIBC[0]}.{RUNTIME_GLIBC[1]}, the runtime's (found {len(candidates)} "
            f"file(s)); the Flatpak installs wheels only"
        )
    return max(ranked, key=lambda pair: (pair[0], pair[1].filename))[1]


def _locked_wheels(package: Mapping[str, Any]) -> list[Wheel]:
    found = []
    for entry in package.get("wheels", []):
        filename = entry["url"].rsplit("/", 1)[-1]
        sha256 = entry["hash"].removeprefix("sha256:")
        found.append(Wheel(package["name"], package["version"], filename, entry["url"], sha256))
    return found


def _marker_holds(marker: str) -> bool | None:
    """Whether an environment marker holds in the Flatpak, or None when it cannot be told.

    Only what uv.lock uses is understood: tests of the form ``variable == 'text'`` or
    ``variable != 'text'`` on the variables of ``FLATPAK_ENVIRONMENT``, joined with ``and`` and
    ``or`` (``and`` binds tighter), without brackets. Anything else is None, never a guess.
    """
    alternatives = []
    for alternative in marker.split(" or "):
        results = []
        for test in alternative.split(" and "):
            parts = _MARKER_TEST.fullmatch(test.strip())
            if parts is None or parts["variable"] not in FLATPAK_ENVIRONMENT:
                return None
            equal = FLATPAK_ENVIRONMENT[parts["variable"]] == parts["value"]
            results.append(equal if parts["operator"] == "==" else not equal)
        alternatives.append(all(results))
    return any(alternatives)


def _wanted_dependencies(package: Mapping[str, Any], extras: Sequence[str]) -> list[Any]:
    optional = package.get("optional-dependencies", {})
    return [*package.get("dependencies", []), *(d for e in extras for d in optional.get(e, []))]


def _runtime_closure(lock: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """The project's dependencies, those of its ``RUNTIME_EXTRAS``, and theirs (with the extras a
    dependency asks for, like ``pikepdf[pdfa]``), without its dev group (name order). A dependency
    whose marker does not hold in the Flatpak is left out."""
    packages = {package["name"]: package for package in lock["package"]}
    roots = [p for p in packages.values() if p.get("source") in PROJECT_SOURCES]
    if len(roots) != 1:
        raise WheelSelectionError(f"expected one project package in the lock, found {len(roots)}")
    wanted: dict[str, Mapping[str, Any]] = {}
    pending = [(roots[0], RUNTIME_EXTRAS)]
    visited: set[tuple[str, tuple[str, ...]]] = set()
    while pending:
        parent, extras = pending.pop()
        for dependency in _wanted_dependencies(parent, extras):
            name = dependency["name"]
            if "marker" in dependency:
                holds = _marker_holds(dependency["marker"])
                if holds is None:
                    raise WheelSelectionError(
                        f"{parent['name']} needs {name} only when {dependency['marker']!r}: "
                        "this environment marker is not understood (only == and != tests on "
                        f"{', '.join(sorted(FLATPAK_ENVIRONMENT))}, joined by and/or). "
                        "Pick the wheels by hand or extend gen_wheel_sources.py."
                    )
                if not holds:
                    continue
            if name not in packages:
                raise WheelSelectionError(f"{name} is a dependency but is not in the lock")
            wanted[name] = packages[name]
            step = (name, tuple(sorted(dependency.get("extra", ()))))
            if step not in visited:
                visited.add(step)
                pending.append((packages[name], step[1]))
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
        f"--only-binary=:all: --no-deps {install_to} -r {requirements}"
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
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
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
