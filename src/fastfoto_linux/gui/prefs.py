"""Remember the scan form between runs: a small JSON file in the user's config folder."""

import contextlib
import json
import logging
import os
import tempfile
from collections.abc import Mapping
from dataclasses import fields
from pathlib import Path
from typing import Any

from fastfoto_linux.gui.form import (
    BACK_CHOICES,
    FEED_CHOICES,
    FIELD_NAMES,
    ScanForm,
    absolute_folder,
)
from fastfoto_linux.scanner import SUPPORTED_DPI

logger = logging.getLogger(__name__)

PREFS_DIR = "fastfoto-linux"
PREFS_FILE = "gui.json"
NOT_REMEMBERED = ("date", "notes")  # they belong to one batch, not to the next
REMEMBERED = tuple(name for name in FIELD_NAMES if name not in NOT_REMEMBERED)
_CHOICES = {"feed": FEED_CHOICES, "backs": BACK_CHOICES, "dpi": SUPPORTED_DPI}
_TYPES = {field.name: field.type for field in fields(ScanForm)}


def prefs_path(env: Mapping[str, str] = os.environ) -> Path:
    """``$XDG_CONFIG_HOME/fastfoto-linux/gui.json`` (``~/.config`` when it is unset or relative).

    The XDG specification says a base directory that is not an absolute path is invalid and
    must be ignored.
    """
    configured = env.get("XDG_CONFIG_HOME") or ""
    if configured and Path(configured).is_absolute():
        return Path(configured) / PREFS_DIR / PREFS_FILE
    return Path(env.get("HOME") or Path.home()) / ".config" / PREFS_DIR / PREFS_FILE


def load_form(path: Path | None = None) -> ScanForm:
    """The remembered form; defaults for anything missing, wrong or unreadable (logged)."""
    path = prefs_path() if path is None else path
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ScanForm()
    except (OSError, ValueError) as error:
        logger.warning("ignoring the settings file %s: %s", path, error)
        return ScanForm()
    if not isinstance(data, dict):
        logger.warning("ignoring the settings file %s: it is not a JSON object", path)
        return ScanForm()
    return ScanForm(**{name: data[name] for name in REMEMBERED if _usable(name, data, path)})


def _usable(name: str, data: Mapping[str, Any], path: Path) -> bool:
    """True when ``data`` has a good value for ``name``; a bad one is logged and skipped."""
    if name not in data:
        return False
    value = data[name]
    kind = _TYPES[name]
    good = isinstance(value, kind) and not (kind is int and isinstance(value, bool))
    if good and name in _CHOICES:
        good = value in _CHOICES[name]
    if not good:
        logger.warning("ignoring %s in %s: %r is not a usable value", name, path, value)
    return good


def save_form(form: ScanForm, path: Path | None = None) -> None:
    """Write the form atomically; raises OSError when the file cannot be written."""
    path = prefs_path() if path is None else path
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {name: getattr(form, name) for name in REMEMBERED}
    data["output_folder"] = absolute_folder(
        form.output_folder
    )  # a relative one means nothing next time
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".gui-", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise
