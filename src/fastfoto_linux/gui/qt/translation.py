"""Install the interface translation: the packaged catalog of one allowlisted language, or none.

Translation files are data that is read at run time, so they are held to a few rules:

* only ``fastfoto_<code>.qm`` of an allowlisted code is read, from the folder inside the package
  (never the working directory, a settings value, or the environment); the folder is reached one
  component at a time through descriptors that refuse links, and the file is opened the same way;
* the file must be a regular file of at most 1 MiB, and its layout must be sound
  (``gui.qmformat``: no dependencies section, no empty or unknown section);
* anything else (missing, too big, refused, not loadable, an exception) leaves the app in English
  and logs a warning without paths;
* what the messages say is not checked here: the packaged file is trusted because its SHA-256 is
  pinned and it is byte-identical to a fresh compile of the reviewed ``.ts`` (docs/translating.md);
* ``translate_message`` returns a translation as it is, and the QML labels use ``Text.PlainText``.
"""

import logging
import os
import stat
from pathlib import Path
from typing import Any

from PySide6.QtCore import QCoreApplication, QTranslator

from fastfoto_linux.gui.i18n import (
    CATALOG_PREFIX,
    DEFAULT_LANGUAGE,
    MESSAGES_CONTEXT,
    catalog_dir,
    ui_language_code,
)
from fastfoto_linux.gui.qmformat import check_catalog

logger = logging.getLogger(__name__)

MAX_CATALOG_BYTES = 1 << 20  # a catalog of a few hundred short messages is some tens of KB

# The installed translator and its language. Qt does not own the translator: it is kept here.
_active: dict[str, Any] = {"code": DEFAULT_LANGUAGE, "translator": None, "data": None}


def default_directory() -> Path:
    return catalog_dir()


def active_code() -> str:
    return _active["code"]


def _open_folder(directory: Path) -> int | None:
    """A descriptor for the folder, opened one path component at a time from ``/``.

    Each step is relative to the descriptor before it and refuses a link, so no part of the path
    can be swapped for a link between a check and the open. A relative path, or one with ``..``,
    is refused.
    """
    if not directory.is_absolute() or ".." in directory.parts:
        return None
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        current = os.open("/", flags)
    except OSError:
        return None
    for part in directory.parts[1:]:
        try:
            following = os.open(part, flags, dir_fd=current)
        except OSError:
            os.close(current)
            return None
        os.close(current)
        current = following
    return current


def _read_catalog(folder: int, name: str) -> bytes | None:
    """The bytes of a regular, small file in the folder: opened without following a link and
    checked on the open descriptor, at most ``MAX_CATALOG_BYTES``."""
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
            dir_fd=folder,
        )
    except OSError:
        return None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_CATALOG_BYTES:
            return None
        data = os.read(descriptor, MAX_CATALOG_BYTES + 1)
    except OSError:
        return None
    finally:
        os.close(descriptor)
    return data if len(data) <= MAX_CATALOG_BYTES else None


def _load(code: str, directory: Path) -> tuple[QTranslator, bytes] | None:
    folder = _open_folder(directory)
    if folder is None:
        logger.warning(
            "the translation folder cannot be opened safely; the interface stays English"
        )
        return None
    try:
        data = _read_catalog(folder, f"{CATALOG_PREFIX}{code}.qm")
    finally:
        os.close(folder)
    if data is None:
        logger.warning("no usable translation file for %r; the interface stays English", code)
        return None
    try:
        check_catalog(data)  # the layout only: see gui/qmformat.py
        translator = QTranslator()
        loaded = translator.load(data)
    except Exception as error:  # a catalog must never stop the app
        logger.warning("the translation file for %r is refused (%s); staying English", code, error)
        return None
    if not loaded:
        logger.warning("the translation file for %r cannot be loaded; staying English", code)
        return None
    return translator, data


def activate(code: object, *, directory: Path | None = None) -> bool:
    """Switch the interface to ``code``; False (and nothing changes) when that cannot be done.

    ``directory`` is a seam for the tests; the app always uses the packaged folder.
    """
    if not isinstance(code, str) or code == DEFAULT_LANGUAGE or ui_language_code(code) != code:
        return False
    loaded = _load(code, default_directory() if directory is None else directory)
    if loaded is None:
        return False
    deactivate()
    translator, data = loaded
    QCoreApplication.installTranslator(translator)
    _active.update(code=code, translator=translator, data=data)  # Qt reads the bytes in place
    return True


def deactivate() -> None:
    """Back to English: remove the installed translator, if any."""
    translator = _active["translator"]
    if translator is not None:
        QCoreApplication.removeTranslator(translator)
    _active.update(code=DEFAULT_LANGUAGE, translator=None, data=None)


def translate_message(text: str) -> str:
    """The translation of a message marked in Python; ``text`` itself when there is none."""
    return QCoreApplication.translate(MESSAGES_CONTEXT, text) if text else text
