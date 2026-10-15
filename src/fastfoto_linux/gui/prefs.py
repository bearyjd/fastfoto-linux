"""Remember the scan form between runs: a small JSON file in the user's config folder."""

import os
from collections.abc import Mapping
from pathlib import Path

from fastfoto_linux.gui.form import ScanForm

PREFS_DIR = "fastfoto-linux"
PREFS_FILE = "gui.json"
NOT_REMEMBERED = ("date", "notes")


def prefs_path(env: Mapping[str, str] = os.environ) -> Path:
    """``$XDG_CONFIG_HOME/fastfoto-linux/gui.json`` (``~/.config`` when it is unset)."""
    raise NotImplementedError


def load_form(path: Path | None = None) -> ScanForm:
    """The remembered form; defaults for anything missing, wrong or unreadable (logged)."""
    raise NotImplementedError


def save_form(form: ScanForm, path: Path | None = None) -> None:
    """Write the form atomically; raises OSError when the file cannot be written."""
    raise NotImplementedError
