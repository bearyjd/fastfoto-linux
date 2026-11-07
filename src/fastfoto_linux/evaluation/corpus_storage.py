"""Where the corpus lives: never a default, never a symlink, never inside the checkout."""

import os
from collections.abc import Mapping
from pathlib import Path

from fastfoto_linux.evaluation.corpus_manifest import CorpusError, check_outside_checkout
from fastfoto_linux.evaluation.redeye_images import open_resolved_dir

ENV_VAR = "FASTFOTO_CORPUS_DIR"
MANIFEST_NAME = "MANIFEST.json"


def _requested(explicit: Path | None, env: Mapping[str, str]) -> str:
    chosen = os.fspath(explicit) if explicit is not None else env.get(ENV_VAR, "")
    if not chosen:
        raise CorpusError(f"no corpus directory: pass one or set {ENV_VAR} (there is no default)")
    if (
        "\0" in chosen
        or not chosen.startswith("/")
        or any(part in (".", "..") for part in chosen.split("/"))
    ):
        raise CorpusError("the corpus directory must be an absolute path without '.' or '..'")
    return chosen


def corpus_root(explicit: Path | None, env: Mapping[str, str]) -> Path:
    """The corpus directory: ``explicit``, else ``$FASTFOTO_CORPUS_DIR``.

    Refused when it is not absolute, has a symlink in its path, does not exist, or is (or is
    inside) a fastfoto-linux checkout, so no corpus file can end up committed by accident.
    """
    root = Path(_requested(explicit, env))
    try:
        os.close(open_resolved_dir(root))  # no symlink component, and it is a directory
    except OSError:
        raise CorpusError("cannot open the corpus directory (symlinks are refused)") from None
    check_outside_checkout(root)
    return root


def manifest_path(explicit: Path | None, env: Mapping[str, str]) -> Path:
    """``<corpus root>/MANIFEST.json``."""
    return corpus_root(explicit, env) / MANIFEST_NAME
