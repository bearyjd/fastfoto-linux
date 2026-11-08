"""Install the interface translation: the packaged catalog of one allowlisted language, or none.

Translation files are data that is read at run time, so they are held to a few rules:

* only ``fastfoto_<code>.qm`` of an allowlisted code is read, from the folder inside the package
  (never the working directory, a settings value, or the environment), through a descriptor
  opened without following links, in a folder whose path holds no link;
* the bytes are read in Python first (``gui.qmformat``): a catalog with a dependencies section
  (Qt would load the catalogs it names), an unknown section, markup, control characters or other
  placeholders than its source is refused;
* a file that is missing, not a regular file, too big or not a catalog leaves the app in English;
* the text of a translation is shown as text (the QML labels use ``Text.PlainText``) and is never
  used as a format string: ``translate_message`` returns it as it is.
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
from fastfoto_linux.gui.qmformat import CatalogError, read_catalog

logger = logging.getLogger(__name__)

MAX_CATALOG_BYTES = 1 << 20  # a catalog of a few hundred short messages is some tens of KB

# The installed translator and its language. Qt does not own the translator: it is kept here.
_active: dict[str, Any] = {"code": DEFAULT_LANGUAGE, "translator": None, "data": None}


def default_directory() -> Path:
    return catalog_dir()


def active_code() -> str:
    return _active["code"]


def _read_catalog(path: Path) -> bytes | None:
    """The bytes of a regular, small file: opened without following a link, checked on the opened
    descriptor (so a file swapped in afterwards is not the one read), at most ``MAX_CATALOG_BYTES``.
    """
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
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


def _plain_folder(directory: Path) -> bool:
    """True when no part of the folder's path is a link: it is its own real path."""
    return os.path.realpath(directory) == os.fspath(directory)


def _load(code: str, directory: Path) -> tuple[QTranslator, bytes] | None:
    if not _plain_folder(directory):
        logger.warning("the translation folder is reached through a link; staying English")
        return None
    data = _read_catalog(directory / f"{CATALOG_PREFIX}{code}.qm")
    if data is None:
        logger.warning("no usable translation file for %r; the interface stays English", code)
        return None
    try:
        read_catalog(data)  # no dependencies, no markup, no odd sections: before Qt sees it
    except CatalogError as error:
        logger.warning("the translation file for %r is refused (%s); staying English", code, error)
        return None
    translator = QTranslator()
    if not translator.load(data):
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
