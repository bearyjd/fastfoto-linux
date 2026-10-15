"""The words the scan page shows: progress, what went wrong, where the raw pages are."""

from dataclasses import dataclass

from fastfoto_linux.gui.state import State
from fastfoto_linux.session import RawReason, SessionResult


@dataclass(frozen=True)
class Banner:
    """A message for the top of the page; ``kind`` is error, warning, info or positive."""

    kind: str
    text: str


def raw_reason_text(reason: RawReason) -> str:
    raise NotImplementedError


def error_text(error: BaseException) -> str:
    """One readable sentence for an exception; scanner problems say what to do."""
    raise NotImplementedError


def progress_text(state: State, pages: int, photos: int) -> str:
    """ "Scanning page N" / "Processing photo N" while busy, empty otherwise."""
    raise NotImplementedError


def result_banner(state: State, result: SessionResult) -> Banner | None:
    """The message a finished session needs, None when it ended cleanly with nothing to say."""
    raise NotImplementedError
