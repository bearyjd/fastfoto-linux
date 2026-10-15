"""Helpers for driving the bridge and the QML window in tests."""

import time
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QCoreApplication, QEvent, QMetaObject, QObject

WAIT = 10.0


def wait_until(predicate: Callable[[], object], what: str, timeout: float = WAIT) -> None:
    """Run the event loop until ``predicate`` is true; fail with ``what`` after ``timeout``."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError(f"timed out waiting for {what}")


def settle() -> None:
    """Deliver everything already queued, including deferred deletes."""
    for _ in range(3):
        QCoreApplication.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def child(root: QObject, name: str) -> Any:
    found = root.findChild(QObject, name)
    assert found is not None, f"no QML object named {name!r}"
    return found


def invoke(item: QObject, method: str) -> None:
    """Call a slot or invokable of a QML object, like ``click()`` or ``accept()``."""
    assert QMetaObject.invokeMethod(item, method)


def click(button: QObject) -> None:
    invoke(button, "click")
