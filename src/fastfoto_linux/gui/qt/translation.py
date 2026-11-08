"""Install the interface translation: the packaged catalog of one allowlisted language, or none.

Translation files are data that is read at run time, so they are held to a few rules:

* only ``fastfoto_<code>.qm`` of an allowlisted code is read, from the folder inside the package
  (never the working directory, a settings value, or the environment);
* a file that is missing, not a regular file, too big or not a catalog leaves the app in English;
* the text of a translation is shown as text (the QML labels use ``Text.PlainText``) and is never
  used as a format string: ``translate_message`` returns it as it is.
"""

import logging
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

logger = logging.getLogger(__name__)

MAX_CATALOG_BYTES = 1 << 20  # a catalog of a few hundred short messages is some tens of KB

# The installed translator and its language. Qt does not own the translator: it is kept here.
_active: dict[str, Any] = {"code": DEFAULT_LANGUAGE, "translator": None}


def default_directory() -> Path:
    return catalog_dir()


def active_code() -> str:
    return _active["code"]


def _usable_file(path: Path) -> bool:
    """True for a regular file (not a link to one, not a folder, not a device) within the limit."""
    try:
        info = path.lstat()
    except OSError:
        return False
    return stat.S_ISREG(info.st_mode) and info.st_size <= MAX_CATALOG_BYTES


def _load(code: str, directory: Path) -> QTranslator | None:
    path = directory / f"{CATALOG_PREFIX}{code}.qm"
    if not _usable_file(path):
        logger.warning("no usable translation file for %r; the interface stays English", code)
        return None
    translator = QTranslator()
    if not translator.load(str(path)):
        logger.warning("the translation file for %r cannot be loaded; staying English", code)
        return None
    return translator


def activate(code: object, *, directory: Path | None = None) -> bool:
    """Switch the interface to ``code``; False (and nothing changes) when that cannot be done.

    ``directory`` is a seam for the tests; the app always uses the packaged folder.
    """
    if not isinstance(code, str) or code == DEFAULT_LANGUAGE or ui_language_code(code) != code:
        return False
    translator = _load(code, default_directory() if directory is None else directory)
    if translator is None:
        return False
    deactivate()
    QCoreApplication.installTranslator(translator)
    _active.update(code=code, translator=translator)
    return True


def deactivate() -> None:
    """Back to English: remove the installed translator, if any."""
    translator = _active["translator"]
    if translator is not None:
        QCoreApplication.removeTranslator(translator)
    _active.update(code=DEFAULT_LANGUAGE, translator=None)


def translate_message(text: str) -> str:
    """The translation of a message marked in Python; ``text`` itself when there is none."""
    return QCoreApplication.translate(MESSAGES_CONTEXT, text) if text else text
