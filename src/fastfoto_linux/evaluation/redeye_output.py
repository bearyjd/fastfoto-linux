"""Where results go: outside the repo, atomically, with private permissions."""

from collections.abc import Mapping
from pathlib import Path

from fastfoto_linux.evaluation.redeye_manifest import Manifest


def resolve_out_dir(manifest: Manifest, out: Path | None, env: Mapping[str, str]) -> Path:
    """``out`` (or the cache default), refused inside the manifest root or the project checkout."""
    raise NotImplementedError


def write_outputs(out_dir: Path, files: Mapping[str, str]) -> None:
    raise NotImplementedError
