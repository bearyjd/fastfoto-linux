"""Paths and loaders shared by the Flatpak packaging tests."""

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
APP_ID = "io.github.bearyjd.FastFotoLinux"
PACKAGING = ROOT / "packaging"
FLATPAK_DIR = PACKAGING / "flatpak"
MANIFEST = FLATPAK_DIR / f"{APP_ID}.yml"
RUNTIME_MODULE = FLATPAK_DIR / "python-deps.json"
BUILD_MODULE = FLATPAK_DIR / "python-build-deps.json"
METAINFO = PACKAGING / f"{APP_ID}.metainfo.xml"
DESKTOP = PACKAGING / f"{APP_ID}.desktop"
ICON = PACKAGING / f"{APP_ID}.svg"
GENERATOR = ROOT / "tools" / "flatpak" / "gen_wheel_sources.py"
CI = ROOT / ".github" / "workflows" / "ci.yml"
SHIM_INSTALL_PATH = "/app/lib/fastfoto-linux/ff680w_usb_gap.so"


def generator() -> ModuleType:
    """The wheel-source generator, loaded from tools/ (which is not a package)."""
    name = "gen_wheel_sources"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, GENERATOR)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_manifest() -> dict[str, Any]:
    assert MANIFEST.is_file(), f"{MANIFEST.relative_to(ROOT)} does not exist"
    loaded = yaml.safe_load(MANIFEST.read_text())
    assert isinstance(loaded, dict)
    return loaded


def load_json(path: Path) -> dict[str, Any]:
    assert path.is_file(), f"{path.relative_to(ROOT)} does not exist"
    loaded = json.loads(path.read_text())
    assert isinstance(loaded, dict)
    return loaded


def modules() -> list[tuple[Path, dict[str, Any]]]:
    """Every module of the manifest, with the folder its relative source paths are from."""
    found: list[tuple[Path, dict[str, Any]]] = []
    for entry in load_manifest()["modules"]:
        if isinstance(entry, str):
            file = MANIFEST.parent / entry
            found.append((file.parent, load_json(file)))
        else:
            found.append((MANIFEST.parent, entry))
    return found


def module(name: str) -> dict[str, Any]:
    for _, found in modules():
        if found["name"] == name:
            return found
    raise AssertionError(f"the manifest has no module named {name!r}")


def commands(entry: dict[str, Any]) -> str:
    """The shell lines a module runs: its build commands, then its post-install commands."""
    return "\n".join([*entry.get("build-commands", []), *entry.get("post-install", [])])
