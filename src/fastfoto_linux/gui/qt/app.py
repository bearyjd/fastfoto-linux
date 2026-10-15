"""``fastfoto``: start the desktop app."""

from collections.abc import Callable
from typing import Any

EXIT_MISSING_QT = 3
APP_ID = "io.github.bearyjd.FastFotoLinux"


def kirigami_available(import_paths: list[str]) -> bool:
    """True when one of the QML import folders has the Kirigami module."""
    raise NotImplementedError


def configure_style() -> None:
    """Use the KDE desktop style for the controls when it is installed."""
    raise NotImplementedError


def create_engine(bridge: Any) -> tuple[Any, list[str]]:
    """The QML engine with the window loaded, and the list its warnings are collected in."""
    raise NotImplementedError


def show_error_dialog(text: str) -> None:
    raise NotImplementedError


def main(run_loop: Callable[[], int] | None = None) -> int:
    """Run the app; returns its exit code (3 when PySide6 or Kirigami is missing)."""
    raise NotImplementedError
