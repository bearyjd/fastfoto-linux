"""The states of the scan page and which moves between them are allowed."""

from collections.abc import Mapping
from enum import StrEnum, auto
from types import MappingProxyType

from fastfoto_linux.session import DocumentSessionResult, SessionResult


class Mode(StrEnum):
    """What the page scans: photos, or documents that become one PDF."""

    PHOTOS = "photos"
    DOCUMENTS = "documents"


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


class ActionBlockedError(InvalidTransitionError):
    """The user asked for something that cannot be done right now; nothing has changed."""


_AFTER_A_SESSION = frozenset({State.CHECKING, State.SCANNING})
_TRANSITIONS: Mapping[State, frozenset[State]] = MappingProxyType(
    {
        State.IDLE: frozenset({State.CHECKING}),
        State.CHECKING: frozenset({State.READY, State.NO_SCANNER}),
        # The pages a cancelled scan kept can be processed once the scanner has been checked
        # again, and processing needs no scanner.
        State.READY: frozenset({State.CHECKING, State.SCANNING, State.PROCESSING}),
        State.NO_SCANNER: frozenset({State.CHECKING, State.PROCESSING}),
        State.SCANNING: frozenset(
            {State.PROCESSING, State.CANCELLING, State.FAILED, State.CANCELLED, State.NO_SCANNER}
        ),
        State.PROCESSING: frozenset({State.CANCELLING, State.DONE, State.FAILED}),
        State.CANCELLING: frozenset({State.CANCELLED, State.DONE, State.FAILED}),
        State.DONE: _AFTER_A_SESSION,
        State.FAILED: _AFTER_A_SESSION | {State.PROCESSING},
        State.CANCELLED: _AFTER_A_SESSION | {State.PROCESSING},
    }
)
_BUSY = frozenset({State.CHECKING, State.SCANNING, State.PROCESSING, State.CANCELLING})
_CANCELLABLE = frozenset({State.SCANNING, State.PROCESSING})


def can_transition(current: State, target: State) -> bool:
    return target in _TRANSITIONS[current]


def transition(current: State, target: State) -> State:
    """``target``, or InvalidTransitionError when the page cannot go there from ``current``."""
    if not can_transition(current, target):
        raise InvalidTransitionError(f"the page cannot go from {current.value} to {target.value}")
    return target


def is_busy(state: State) -> bool:
    """True while something is running that the user has to wait for or cancel."""
    return state in _BUSY


def can_cancel(state: State) -> bool:
    return state in _CANCELLABLE


def final_state(result: SessionResult | DocumentSessionResult) -> State:
    """Where a finished session leaves the page: FAILED, CANCELLED or DONE."""
    if result.error is not None:
        return State.FAILED
    return State.CANCELLED if result.cancelled else State.DONE
