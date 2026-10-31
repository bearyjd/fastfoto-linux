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

from fastfoto_linux.cli.options import FEED_FACE_DOWN, FEED_FACE_UP
from fastfoto_linux.gui.docform import (
    DOCUMENT_CLEANUPS,
    DOCUMENT_COLOURS,
    DOCUMENT_FIELD_NAMES,
    DocumentForm,
)
from fastfoto_linux.gui.form import (
    BACK_CHOICES,
    FEED_CHOICES,
    FIELD_NAMES,
    PRESET_CHOICES_WITH_STANDARD,
    ScanForm,
    absolute_folder,
)
from fastfoto_linux.gui.state import Mode
from fastfoto_linux.scanner import SUPPORTED_DPI
from fastfoto_linux.session import DOCUMENT_DPI

logger = logging.getLogger(__name__)

PREFS_DIR = "fastfoto-linux"
PREFS_FILE = "gui.json"
NOT_REMEMBERED = ("date", "notes")  # they belong to one batch, not to the next
REMEMBERED = tuple(name for name in FIELD_NAMES if name not in NOT_REMEMBERED)
DOCUMENTS_KEY = "documents"  # the Documents form lives under this key, the Photos one is flat
MODE_KEY = "mode"
OLD_FEED_KEY = (
    "feed"  # what the loading direction was stored as, with the names the wrong way round
)
_FROM_OLD_FEED = {FEED_FACE_DOWN: FEED_FACE_UP, FEED_FACE_UP: FEED_FACE_DOWN}
_CHOICES = {
    "loaded": FEED_CHOICES,
    "backs": BACK_CHOICES,
    "dpi": SUPPORTED_DPI,
    "preset": PRESET_CHOICES_WITH_STANDARD,
}
_TYPES = {field.name: field.type for field in fields(ScanForm)}
_DOCUMENT_CHOICES = {
    "colour": DOCUMENT_COLOURS,
    "dpi": DOCUMENT_DPI,
    "cleanup": DOCUMENT_CLEANUPS,
    "preset": PRESET_CHOICES_WITH_STANDARD,
}
_DOCUMENT_TYPES = {field.name: field.type for field in fields(DocumentForm)}


def prefs_path(env: Mapping[str, str] = os.environ) -> Path:
    """``$XDG_CONFIG_HOME/fastfoto-linux/gui.json`` (``~/.config`` when it is unset or relative).

    The XDG specification says a base directory that is not an absolute path is invalid and
    must be ignored.
    """
    configured = env.get("XDG_CONFIG_HOME") or ""
    if configured and Path(configured).is_absolute():
        return Path(configured) / PREFS_DIR / PREFS_FILE
    return Path(env.get("HOME") or Path.home()) / ".config" / PREFS_DIR / PREFS_FILE


def _read_object(path: Path) -> dict[str, Any] | None:
    """The settings file as a JSON object; None (logged unless it is simply missing) if not."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as error:
        logger.warning("ignoring the settings file %s: %s", path, error)
        return None
    if not isinstance(data, dict):
        logger.warning("ignoring the settings file %s: it is not a JSON object", path)
        return None
    return data


def _migrated(data: dict[str, Any]) -> dict[str, Any]:
    """``data`` with an old ``feed`` entry read as ``loaded``; ``loaded`` wins when both are there.

    The old entry named the loading the wrong way round: its "face-down" meant the back is
    scanned first, which is "face-up" now (and the other way round). A value that is not one of
    the two is kept as it is, so that it is logged and skipped like any other.
    """
    if "loaded" in data or OLD_FEED_KEY not in data:
        return data
    old = data[OLD_FEED_KEY]
    return {**data, "loaded": _FROM_OLD_FEED.get(old, old) if isinstance(old, str) else old}


def load_form(path: Path | None = None) -> ScanForm:
    """The remembered form; defaults for anything missing, wrong or unreadable (logged)."""
    path = prefs_path() if path is None else path
    data = _read_object(path)
    if data is None:
        return ScanForm()
    data = _migrated(data)
    return ScanForm(**{name: data[name] for name in REMEMBERED if _usable(name, data, path)})


def load_document_form(path: Path | None = None) -> DocumentForm:
    """The remembered Documents form; defaults for anything missing or wrong (logged)."""
    path = prefs_path() if path is None else path
    data = _read_object(path)
    section = None if data is None else data.get(DOCUMENTS_KEY)
    if not isinstance(section, dict):
        if section is not None:
            logger.warning("ignoring %s in %s: it is not a JSON object", DOCUMENTS_KEY, path)
        return DocumentForm()
    usable = (
        name
        for name in DOCUMENT_FIELD_NAMES
        if _usable(name, section, path, types=_DOCUMENT_TYPES, choices=_DOCUMENT_CHOICES)
    )
    return DocumentForm(**{name: section[name] for name in usable})


def load_mode(path: Path | None = None) -> Mode:
    """The mode the app was left in; Photos for anything missing or unknown."""
    path = prefs_path() if path is None else path
    data = _read_object(path)
    value = None if data is None else data.get(MODE_KEY)
    if isinstance(value, str) and value in {mode.value for mode in Mode}:
        return Mode(value)
    if value is not None:
        logger.warning("ignoring %s in %s: %r is not a mode", MODE_KEY, path, value)
    return Mode.PHOTOS


def _usable(
    name: str,
    data: Mapping[str, Any],
    path: Path,
    *,
    types: Mapping[str, Any] = _TYPES,
    choices: Mapping[str, Any] = _CHOICES,
) -> bool:
    """True when ``data`` has a good value for ``name``; a bad one is logged and skipped."""
    if name not in data:
        return False
    value = data[name]
    kind = types[name]
    good = isinstance(value, kind) and not (kind is int and isinstance(value, bool))
    if good and name in choices:
        good = value in choices[name]
    if not good:
        logger.warning("ignoring %s in %s: %r is not a usable value", name, path, value)
    return good


def save_form(form: ScanForm, path: Path | None = None) -> None:
    """Write the form atomically; raises OSError when the file cannot be written.

    Everything else in the file (the Documents settings, the mode, what a newer version wrote)
    is kept.
    """
    data = {name: getattr(form, name) for name in REMEMBERED}
    data["output_folder"] = absolute_folder(
        form.output_folder
    )  # a relative one means nothing next time
    _update(prefs_path() if path is None else path, data)


def save_document_form(form: DocumentForm, path: Path | None = None) -> None:
    """Write the Documents form atomically, keeping the rest of the file (see ``save_form``)."""
    path = prefs_path() if path is None else path
    section = _existing(path).get(DOCUMENTS_KEY)
    kept = section if isinstance(section, dict) else {}
    mine = {name: getattr(form, name) for name in DOCUMENT_FIELD_NAMES}
    _update(path, {DOCUMENTS_KEY: {**kept, **mine}})


def save_mode(mode: Mode, path: Path | None = None) -> None:
    """Write the mode atomically, keeping the rest of the file (see ``save_form``)."""
    _update(prefs_path() if path is None else path, {MODE_KEY: Mode(mode).value})


def _existing(path: Path) -> dict[str, Any]:
    """What the file holds now, or nothing when it is missing or unusable (a save replaces it)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _update(path: Path, changes: Mapping[str, Any]) -> None:
    """Write the file again with ``changes`` over what it holds: atomically, or not at all."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {**_existing(path), **changes}
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
