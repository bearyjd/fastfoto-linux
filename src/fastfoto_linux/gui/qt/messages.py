"""Hides two console lines from KDE's own code that are known to be harmless.

Only these two exact messages are dropped; every other message goes where it went before (to
the previous Qt message handler, or to stderr in Qt's default format when there was none).
"""

import os
import re
import sys
from collections.abc import Callable
from posixpath import basename
from typing import Any
from urllib.parse import urlsplit

from fastfoto_linux.session.raw import TEMP_PREFIX

# kf6-qqc2-desktop-style gives every text field a context menu (private/TextFieldContextMenu.qml).
# Its items show their shortcuts through org/kde/desktop/MenuItem.qml (line 85, a
# `Shortcut { sequence: action.shortcut }`), and StandardKey.Copy has three key bindings, so Qt
# warns each time the menu is built. The app has no shortcuts of its own and Copy works.
SHORTCUT_FILE = "org/kde/desktop/MenuItem.qml"
SHORTCUT_TEXT = "Only binding to one of multiple key bindings associated with"

# KDE's folder dialog (kio-widgets, KDirModel) watches the output folder. The session's hidden
# temporary folder in it is renamed to .raw/<stamp> by design (session/raw.py), so the watcher
# sees an entry it never listed disappear and reports it.
KDIRMODEL_CATEGORY = "kf.kio.widgets.kdirmodel"
_KDIRMODEL_REMOVED = re.compile(
    r'No node found for item that was just removed: QUrl\("(?P<url>[^"]*)"\)\s*$'
)


def _is_shortcut_warning(file: str | None, text: str) -> bool:
    return file is not None and file.endswith("/" + SHORTCUT_FILE) and SHORTCUT_TEXT in text


def _is_removed_temp_folder(category: str | None, text: str) -> bool:
    if category != KDIRMODEL_CATEGORY:
        return False
    removed = _KDIRMODEL_REMOVED.match(text)
    if removed is None:
        return False
    path = urlsplit(removed.group("url")).path.rstrip("/")
    return basename(path).startswith(TEMP_PREFIX)


def is_known_noise(category: str | None, file: str | None, text: str) -> bool:
    """True for the two KDE lines that are hidden; False for every other message."""
    return _is_shortcut_warning(file, text) or _is_removed_temp_folder(category, text)


def _print_like_qt(kind: Any, context: Any, text: str) -> None:
    """What Qt's own handler does: print the message in the default format, abort on a fatal one."""
    from PySide6.QtCore import QtMsgType, qFormatLogMessage  # noqa: PLC0415

    if sys.stderr is not None:
        sys.stderr.write(qFormatLogMessage(kind, context, text) + "\n")
        sys.stderr.flush()
    if kind == QtMsgType.QtFatalMsg:
        os.abort()


def filtering_handler(previous: Callable[..., None] | None) -> Callable[[Any, Any, str], None]:
    """A Qt message handler that drops the known lines and passes the rest on.

    ``previous`` is the handler that was installed before (``None`` for Qt's default one). It may
    be called from any thread, as Qt's handlers are, so it keeps no state.
    """

    def handle(kind: Any, context: Any, text: str) -> None:
        if is_known_noise(context.category, context.file, text):
            return
        if previous is None:
            _print_like_qt(kind, context, text)
        else:
            previous(kind, context, text)

    return handle


def install_message_filter() -> Callable[[], None]:
    """Install the handler; returns the function that puts the previous one back."""
    from PySide6.QtCore import qInstallMessageHandler  # noqa: PLC0415

    previous = qInstallMessageHandler(None)
    qInstallMessageHandler(filtering_handler(previous))

    def undo() -> None:
        qInstallMessageHandler(previous)

    return undo
