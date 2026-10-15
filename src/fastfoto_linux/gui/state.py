"""The states of the scan page and which moves between them are allowed."""

from enum import StrEnum, auto

from fastfoto_linux.session import SessionResult


class State(StrEnum):
    IDLE = auto()
    CHECKING = auto()
    READY = auto()
    NO_SCANNER = auto()
    SCANNING = auto()
    PROCESSING = auto()
    CANCELLING = auto()
    DONE = auto()
    FAILED = auto()
    CANCELLED = auto()


class InvalidTransitionError(RuntimeError):
    """A move the scan page never makes: it is a bug, not something the user did."""


def can_transition(current: State, target: State) -> bool:
    raise NotImplementedError


def transition(current: State, target: State) -> State:
    """``target``, or InvalidTransitionError when the page cannot go there from ``current``."""
    raise NotImplementedError


def is_busy(state: State) -> bool:
    """True while something is running that the user has to wait for or cancel."""
    raise NotImplementedError


def can_cancel(state: State) -> bool:
    raise NotImplementedError


def final_state(result: SessionResult) -> State:
    """Where a finished session leaves the page: CANCELLED, FAILED or DONE."""
    raise NotImplementedError
