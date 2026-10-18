"""Asynchronous local OCR inventory and explicit model downloads for the language picker."""

from typing import Any

from PySide6.QtCore import QObject

from fastfoto_linux.gui.controller import Controller


class LanguagesView(QObject):
    def __init__(self, controller: Controller, parent: QObject | None = None, **tools: Any) -> None:
        super().__init__(parent)

    def reload(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        pass
