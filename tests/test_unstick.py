"""The pre-scan check's protocol, against a fake scanner (no USB, no sleeping)."""

import logging
import threading

import pytest

from fastfoto_linux.scanner import unstick
from fastfoto_linux.scanner.errors import ScanCancelledError, ScannerStuckError
from fastfoto_linux.scanner.unstick import Outcome
from tests.unstick_fakes import (
    STUCK_NEEDS_BYTES,
    FakeClock,
    FakeScanner,
    cancel_after_reads,
)

LOGGER = "fastfoto_linux.scanner.unstick"


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


def check(scanner: FakeScanner, **options):
    return unstick.ensure_ready(scanner, clock=scanner.clock, **options)


# --- a healthy scanner -------------------------------------------------------------------------


def test_a_healthy_scanner_gets_hello_then_fin_and_nothing_else(clock: FakeClock) -> None:
    scanner = FakeScanner(clock, swallow=0)

    result = check(scanner)

    assert result.outcome is Outcome.HEALTHY
    assert result.filler_bytes == 0
    assert scanner.writes == [unstick.HELLO, unstick.FIN]


def test_the_fin_reply_is_read_so_scanimage_does_not_find_it_in_the_pipe(clock: FakeClock) -> None:
    scanner = FakeScanner(clock)

    check(scanner)

    assert scanner.unread == 0


def test_stale_input_is_drained_before_the_hello(clock: FakeClock) -> None:
    scanner = FakeScanner(clock, stale=(b"old reply", b"older reply"))

    result = check(scanner)

    assert result.outcome is Outcome.HEALTHY
    assert scanner.writes == [unstick.HELLO, unstick.FIN]  # the stale bytes were not its answer


def test_a_slow_but_healthy_scanner_is_never_sent_filler(clock: FakeClock) -> None:
    scanner = FakeScanner(clock, reply_after_s=2.0)

    result = check(scanner)

    assert result.outcome is Outcome.HEALTHY
    assert scanner.filler_bytes == 0
    assert scanner.writes == [unstick.HELLO, unstick.FIN]
    assert clock.now >= 2.0


def test_a_reply_that_is_not_an_ack_is_recovered_without_filler(clock: FakeClock) -> None:
    scanner = FakeScanner(clock, hello_reply=b"\x15")

    result = check(scanner)

    assert result.outcome is Outcome.FREED
    assert scanner.writes == [unstick.HELLO, unstick.FIN, unstick.HELLO, unstick.FIN]


# --- a stuck scanner ---------------------------------------------------------------------------


def test_a_stuck_scanner_is_freed_with_filler_then_fin_and_verified(clock: FakeClock) -> None:
    scanner = FakeScanner(clock, swallow=STUCK_NEEDS_BYTES)

    result = check(scanner)

    assert result.outcome is Outcome.FREED
    chunks = scanner.writes[1:-3]
    assert scanner.writes[0] == unstick.HELLO
    assert chunks
    assert all(chunk == b" " * 64 for chunk in chunks)  # 0x20 filler, 64 bytes at a time
    assert scanner.writes[-3:] == [unstick.FIN, unstick.HELLO, unstick.FIN]
    assert result.filler_bytes == scanner.filler_bytes == 64 * len(chunks)
    assert 2 + result.filler_bytes >= STUCK_NEEDS_BYTES  # it stopped as soon as it was answered
    assert 2 + result.filler_bytes - 64 < STUCK_NEEDS_BYTES


def test_filler_starts_only_after_the_hello_wait_ran_out(clock: FakeClock) -> None:
    scanner = FakeScanner(clock, swallow=STUCK_NEEDS_BYTES)
    first_filler_at: list[float] = []

    def note(fake: FakeScanner) -> None:
        if fake.filler_bytes and not first_filler_at:
            first_filler_at.append(clock.now)

    scanner.on_read = note
    check(scanner)

    assert first_filler_at
    assert first_filler_at[0] >= unstick.HELLO_WAIT_S


def test_a_scanner_that_never_answers_is_a_stuck_error_after_capped_filler(
    clock: FakeClock,
) -> None:
    scanner = FakeScanner(clock, swallow=None)

    with pytest.raises(ScannerStuckError, match="isn't answering"):
        check(scanner)

    assert 0 < scanner.filler_bytes <= unstick.MAX_FILLER_BYTES
    assert scanner.writes[0] == unstick.HELLO
    assert unstick.FIN not in scanner.writes  # no point ending a session it never began


def test_the_stuck_message_tells_the_user_what_to_do(clock: FakeClock) -> None:
    with pytest.raises(ScannerStuckError) as excinfo:
        check(FakeScanner(clock, swallow=None))

    assert (
        str(excinfo.value) == "The scanner isn't answering. Switch it off and on, then try again."
    )


def test_a_scanner_that_answers_the_filler_but_not_the_hello_after_it_is_stuck(
    clock: FakeClock,
) -> None:
    scanner = FakeScanner(clock, swallow=STUCK_NEEDS_BYTES, recovers=False)

    with pytest.raises(ScannerStuckError):
        check(scanner)

    assert scanner.writes[-2:] == [unstick.FIN, unstick.HELLO]  # verified, and failed


def test_a_failing_send_means_the_scanner_is_stuck(clock: FakeClock) -> None:
    scanner = FakeScanner(clock, fail_writes=True)

    with pytest.raises(ScannerStuckError):
        check(scanner)


# --- cancel ------------------------------------------------------------------------------------


def test_cancel_during_the_hello_wait_stops_the_check_within_one_poll(clock: FakeClock) -> None:
    cancel = threading.Event()
    scanner = FakeScanner(clock, swallow=None)
    scanner.on_read = cancel_after_reads(2, cancel)

    with pytest.raises(ScanCancelledError):
        check(scanner, cancel=cancel)

    assert scanner.writes == [unstick.HELLO]
    assert clock.now <= 2 * unstick.POLL_MS / 1000 + 0.01


def test_cancel_during_the_filler_stops_sending(clock: FakeClock) -> None:
    cancel = threading.Event()
    scanner = FakeScanner(clock, swallow=None)

    def when_filling(fake: FakeScanner) -> None:
        if fake.filler_bytes >= 3 * 64:
            cancel.set()

    scanner.on_read = when_filling

    with pytest.raises(ScanCancelledError):
        check(scanner, cancel=cancel)

    assert scanner.filler_bytes == 3 * 64


# --- what is logged ----------------------------------------------------------------------------


def test_a_freed_scanner_is_logged_at_info(
    clock: FakeClock, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER)

    check(FakeScanner(clock, swallow=STUCK_NEEDS_BYTES))

    infos = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert any("scanner was stuck; freed it" in message for message in infos)


def test_a_healthy_scanner_is_not_reported_at_info(
    clock: FakeClock, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER)

    check(FakeScanner(clock))

    assert [r for r in caplog.records if r.levelno >= logging.INFO] == []


def test_logs_name_commands_but_never_carry_data_bytes(
    clock: FakeClock, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER)

    check(FakeScanner(clock, swallow=STUCK_NEEDS_BYTES))

    text = "\n".join(r.getMessage() for r in caplog.records)
    assert text  # something was logged at debug
    for forbidden in ("parFAIL", "PARA", "x1c", "\\x", "b'", "0x20", "20 20"):
        assert forbidden not in text
