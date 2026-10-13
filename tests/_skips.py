"""Decide when tests needing private scans or a connected scanner may run.

Kept separate from conftest.py so the rules themselves are unit-tested.
"""

from collections.abc import Mapping
from pathlib import Path

SCAN_SUFFIXES = frozenset({".png", ".tif", ".tiff", ".jpg", ".jpeg"})


def scans_dir_from_env(env: Mapping[str, str], default: Path) -> Path:
    raw = env.get("FASTFOTO_REAL_SCANS") or str(default)
    if raw.startswith("~") and env.get("HOME"):
        raw = env["HOME"] + raw[1:]
    return Path(raw).expanduser().resolve()


def has_scans(directory: Path) -> bool:
    if not directory.is_dir():
        return False
    return any(p.suffix.lower() in SCAN_SUFFIXES for p in directory.rglob("*") if p.is_file())


def skip_reason(marker: str, env: Mapping[str, str], scans_dir: Path) -> str | None:
    in_ci = bool(env.get("CI"))
    if marker == "real_scans":
        if in_ci:
            return "private scans never run in CI"
        if not has_scans(scans_dir):
            return f"private scans not found in {scans_dir}"
    if marker == "hardware":
        if in_ci:
            return "no scanner in CI"
        if env.get("FASTFOTO_HARDWARE") != "1":
            return "set FASTFOTO_HARDWARE=1 with an FF-680W connected"
    return None
