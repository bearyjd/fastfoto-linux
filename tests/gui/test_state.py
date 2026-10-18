import pytest

from fastfoto_linux.gui.state import (
    InvalidTransitionError,
    State,
    can_cancel,
    can_transition,
    final_state,
    is_busy,
    transition,
)
from fastfoto_linux.scanner import ScanError
from fastfoto_linux.session import SessionResult

ALLOWED = [
    (State.IDLE, State.CHECKING),
    (State.CHECKING, State.READY),
    (State.CHECKING, State.NO_SCANNER),
    (State.READY, State.CHECKING),
    (State.READY, State.SCANNING),
    (State.READY, State.PROCESSING),  # the pages a cancel kept can be processed after a check
    (State.NO_SCANNER, State.CHECKING),
    (State.NO_SCANNER, State.PROCESSING),  # processing needs no scanner
    (State.SCANNING, State.PROCESSING),
    (State.SCANNING, State.CANCELLING),
    (State.SCANNING, State.FAILED),
    (State.SCANNING, State.CANCELLED),
    (State.SCANNING, State.NO_SCANNER),
    (State.PROCESSING, State.CANCELLING),
    (State.PROCESSING, State.DONE),
    (State.PROCESSING, State.FAILED),
    (State.CANCELLING, State.CANCELLED),
    (State.CANCELLING, State.DONE),
    (State.CANCELLING, State.FAILED),
    (State.DONE, State.CHECKING),
    (State.DONE, State.SCANNING),
    (State.FAILED, State.CHECKING),
    (State.FAILED, State.SCANNING),
    (State.FAILED, State.PROCESSING),
    (State.CANCELLED, State.CHECKING),
    (State.CANCELLED, State.SCANNING),
    (State.CANCELLED, State.PROCESSING),
    (State.PROCESSING, State.REVIEWING),
    (State.CANCELLING, State.REVIEWING),
    (State.REVIEWING, State.PROCESSING),
    (State.REVIEWING, State.CHECKING),
    (State.READY, State.REVIEWING),
    (State.NO_SCANNER, State.REVIEWING),
    (State.DONE, State.REVIEWING),
    (State.DONE, State.PROCESSING),
    (State.FAILED, State.REVIEWING),
    (State.CANCELLED, State.REVIEWING),
]


@pytest.mark.parametrize(("current", "target"), ALLOWED)
def test_the_page_makes_these_moves(current: State, target: State) -> None:
    assert can_transition(current, target)
    assert transition(current, target) is target


def test_every_other_move_raises() -> None:
    allowed = set(ALLOWED)
    for current in State:
        for target in State:
            if (current, target) in allowed:
                continue
            assert not can_transition(current, target)
            with pytest.raises(InvalidTransitionError, match=target.value):
                transition(current, target)


def test_no_state_moves_to_itself() -> None:
    assert not any(can_transition(state, state) for state in State)


def test_the_busy_states_are_the_ones_to_wait_for() -> None:
    busy = {state for state in State if is_busy(state)}
    assert busy == {State.CHECKING, State.SCANNING, State.PROCESSING, State.CANCELLING}


def test_only_scanning_and_processing_can_be_cancelled() -> None:
    assert {state for state in State if can_cancel(state)} == {State.SCANNING, State.PROCESSING}


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (SessionResult(), State.DONE),
        (SessionResult(cancelled=True), State.CANCELLED),
        (SessionResult(error=ScanError("boom")), State.FAILED),
        (SessionResult(error=ScanError("boom"), cancelled=True), State.FAILED),
    ],
)
def test_the_result_decides_where_a_finished_session_leaves_the_page(
    result: SessionResult, expected: State
) -> None:
    assert final_state(result) is expected
