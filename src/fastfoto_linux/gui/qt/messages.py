"""Hides two console lines from KDE's own code that are known to be harmless."""

from collections.abc import Callable
from typing import Any


def is_known_noise(category: str | None, file: str | None, text: str) -> bool:
    """True for the two KDE lines that are hidden; False for every other message."""
    raise NotImplementedError


def filtering_handler(previous: Callable[..., None] | None) -> Callable[[Any, Any, str], None]:
    """A Qt message handler that drops the known lines and passes the rest on."""
    raise NotImplementedError


def install_message_filter() -> Callable[[], None]:
    """Install the handler; returns the function that puts the previous one back."""
    raise NotImplementedError
