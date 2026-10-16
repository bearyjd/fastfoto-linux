"""The pre-scan check's protocol, against a fake scanner (no USB, no sleeping)."""

import logging
from typing import Any

import pytest

from fastfoto_linux.scanner import unstick
from fastfoto_linux.scanner.errors import (
    ScanCancelledError,
    ScannerDisconnectedError,
    ScannerStuckError,
)
from fastfoto_linux.scanner.unstick import DeviceGoneError, Outcome
from tests.unstick_fakes import (
    FIN_REPLY,
    STUCK_NEEDS_BYTES,
    CancelProbe,
    FakeClock,
    FakeScanner,
    cancel_after_reads,
)

LOGGER = "fastfoto_linux.scanner.unstick"
FOREVER_S = 1e9
CANCEL_LATENCY_S = 0.31  # a cancel is noticed within one slice of a wait
NO_ANSWER = (
    "The scanner isn't answering. It may be busy with another device, or stuck — "
    "switch it off and on, then try again."
)
STUCK = "The scanner isn't answering. Switch it off and on, then try again."
DISAPPEARED = "The scanner disappeared (it may have restarted) — try again."


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


def check(scanner: FakeScanner, **options):
    """The check as it runs with no evidence that this is our own stuck session: no filler."""
    return unstick.ensure_ready(scanner, clock=scanner.clock, **options)


def check_allowed(scanner: FakeScanner, **options):
    """The check when filler is allowed (our own previous scan ended badly on this address)."""
    return check(scanner, allow_filler=True, **options)


def freed_logged(caplog: pytest.LogCaptureFixture) -> bool:
    return any("freed it" in r.getMessage() for r in caplog.records)


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


def test_whatever_follows_the_fin_reply_is_drained_too(clock: FakeClock) -> None:
    scanner = FakeScanner(clock, after_fin=(b"late one", b"late two"))

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


@pytest.mark.parametrize("allowed", [False, True], ids=["no-evidence", "evidence"])
def test_a_scanner_that_wakes_after_12_seconds_is_never_sent_filler(
    clock: FakeClock, caplog: pytest.LogCaptureFixture, allowed: bool
) -> None:
    """A dozing scanner was seen answering after about this long: no filler, no "freed it"."""
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    scanner = FakeScanner(clock, reply_after_s=12.0)

    result = unstick.ensure_ready(scanner, clock=clock, allow_filler=allowed)

    assert result.outcome is Outcome.HEALTHY
    assert scanner.filler_bytes == 0
    assert scanner.writes == [unstick.HELLO, unstick.FIN]
    assert clock.now >= 12.0
    assert not freed_logged(caplog)


@pytest.mark.parametrize("reply", [b"\x15", FIN_REPLY], ids=["nak", "stale-fin-reply"])
def test_a_reply_that_is_not_an_ack_is_recovered_without_filler_and_not_called_freed(
    clock: FakeClock, caplog: pytest.LogCaptureFixture, reply: bytes
) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    scanner = FakeScanner(clock, hello_reply=reply)

    result = check(scanner)

    assert result.outcome is Outcome.HEALTHY
    assert result.filler_bytes == 0
    assert scanner.writes == [unstick.HELLO, unstick.FIN, unstick.HELLO, unstick.FIN]
    assert not freed_logged(caplog)


# --- a silent scanner and the evidence needed to send it filler --------------------------------


@pytest.mark.parametrize("swallow", [None, STUCK_NEEDS_BYTES], ids=["dead", "stuck"])
def test_a_silent_hello_without_evidence_sends_nothing_more(
    clock: FakeClock, swallow: int | None
) -> None:
    """It may be busy with another device over Wi-Fi: filler would corrupt that session."""
    scanner = FakeScanner(clock, swallow=swallow)

    with pytest.raises(ScannerStuckError) as excinfo:
        check(scanner)

    assert str(excinfo.value) == NO_ANSWER
    assert scanner.writes == [unstick.HELLO]  # no filler, and no FIN for a session never begun


def test_a_silent_hello_waits_the_whole_hello_time_before_giving_up(clock: FakeClock) -> None:
    with pytest.raises(ScannerStuckError):
        check(FakeScanner(clock, swallow=None))

    assert 15.0 <= clock.now <= 17.0


def test_filler_starts_only_after_the_hello_wait_ran_out(clock: FakeClock) -> None:
    scanner = FakeScanner(clock, swallow=STUCK_NEEDS_BYTES)
    first_filler_at: list[float] = []

    def note(fake: FakeScanner) -> None:
        if fake.write_attempts == 2 and not first_filler_at:  # the write after the hello
            first_filler_at.append(clock.now)

    scanner.on_write = note
    check_allowed(scanner)

    assert first_filler_at
    assert 15.0 <= first_filler_at[0] <= 17.0  # a hello wait of 5 s or of 30 s fails this


# --- a stuck scanner, with the evidence --------------------------------------------------------


def test_a_stuck_scanner_is_freed_with_filler_then_fin_and_verified(clock: FakeClock) -> None:
    scanner = FakeScanner(clock, swallow=STUCK_NEEDS_BYTES)

    result = check_allowed(scanner)

    assert result.outcome is Outcome.FREED
    chunks = scanner.writes[1:-3]
    assert scanner.writes[0] == unstick.HELLO
    assert chunks
    assert all(chunk == b" " * 64 for chunk in chunks)  # 0x20 filler, 64 bytes at a time
    assert scanner.writes[-3:] == [unstick.FIN, unstick.HELLO, unstick.FIN]
    assert result.filler_bytes == scanner.filler_bytes == 64 * len(chunks)
    assert 2 + result.filler_bytes >= STUCK_NEEDS_BYTES  # it stopped as soon as it was answered
    assert 2 + result.filler_bytes - 64 < STUCK_NEEDS_BYTES


def test_a_scanner_that_never_answers_is_a_stuck_error_after_exactly_8_kib_of_filler(
    clock: FakeClock,
) -> None:
    scanner = FakeScanner(clock, swallow=None)

    with pytest.raises(ScannerStuckError, match="isn't answering"):
        check_allowed(scanner)

    assert scanner.filler_bytes == 8192
    assert scanner.writes[0] == unstick.HELLO
    assert unstick.FIN not in scanner.writes  # no point ending a session it never began


def test_after_filler_that_did_not_help_the_message_says_to_switch_it_off_and_on(
    clock: FakeClock,
) -> None:
    with pytest.raises(ScannerStuckError) as excinfo:
        check_allowed(FakeScanner(clock, swallow=None))

    assert str(excinfo.value) == STUCK


def test_a_scanner_that_answers_the_filler_but_not_the_hello_after_it_is_stuck(
    clock: FakeClock,
) -> None:
    scanner = FakeScanner(clock, swallow=STUCK_NEEDS_BYTES, recovers=False)

    with pytest.raises(ScannerStuckError):
        check_allowed(scanner)

    assert scanner.writes[-2:] == [unstick.FIN, unstick.HELLO]  # verified, and failed


def test_a_failing_send_means_the_scanner_is_stuck(clock: FakeClock) -> None:
    scanner = FakeScanner(clock, fail_writes=True)

    with pytest.raises(ScannerStuckError):
        check(scanner)


# --- a scanner that refuses an OUT while it wakes up -------------------------------------------


def test_an_out_the_scanner_refuses_for_9_seconds_is_retried_and_the_check_goes_on(
    clock: FakeClock,
) -> None:
    scanner = FakeScanner(clock, refuse_out_until_s=9.0)

    result = check(scanner)

    assert result.outcome is Outcome.HEALTHY
    assert scanner.writes == [unstick.HELLO, unstick.FIN]
    assert clock.now >= 9.0


def test_an_out_that_is_never_accepted_ends_the_check_after_a_budget_of_10_to_20_seconds(
    clock: FakeClock,
) -> None:
    scanner = FakeScanner(clock, refuse_out_until_s=FOREVER_S)

    with pytest.raises(ScannerStuckError) as excinfo:
        check(scanner)

    assert str(excinfo.value) == NO_ANSWER
    assert 10.0 <= clock.now <= 20.0  # a budget of 5 s or of 60 s fails this
    assert scanner.writes == []


def test_every_out_is_asked_for_in_slices_short_enough_to_cancel(clock: FakeClock) -> None:
    scanner = FakeScanner(clock)

    check(scanner)

    assert scanner.write_timeouts
    assert all(0 < timeout_ms <= 250 for timeout_ms in scanner.write_timeouts)


def test_a_partly_accepted_out_continues_with_what_is_left(clock: FakeClock) -> None:
    scanner = FakeScanner(clock, accept_per_call=1)

    result = check(scanner)

    assert result.outcome is Outcome.HEALTHY
    assert scanner.stream == unstick.HELLO + unstick.FIN  # nothing sent twice, nothing lost
    assert scanner.writes[:2] == [b"\x1c", b"X"]


def test_a_refused_fin_after_the_scanner_said_ack_is_not_fatal(
    clock: FakeClock, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    scanner = FakeScanner(clock, refuse_out_until_s=FOREVER_S, refuse_only=unstick.FIN)

    result = check(scanner)

    assert result.outcome is Outcome.HEALTHY
    assert scanner.writes == [unstick.HELLO]
    assert clock.now <= 40.0
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []
    assert any("FIN" in r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG)


def test_a_fin_that_fails_after_the_scanner_said_ack_is_not_fatal(clock: FakeClock) -> None:
    scanner = FakeScanner(
        clock, write_error=unstick.TransportError("bulk OUT: I/O error"), error_on=unstick.FIN
    )

    result = check(scanner)

    assert result.outcome is Outcome.HEALTHY


# --- the scanner vanishes ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "options",
    [
        {"write_error": DeviceGoneError("no such device")},
        {"read_error": DeviceGoneError("no such device")},
        {"write_error": DeviceGoneError("no such device"), "error_on": unstick.FIN},
    ],
    ids=["hello", "read", "fin"],
)
def test_a_scanner_that_is_gone_says_so_wherever_it_happens(
    clock: FakeClock, options: dict[str, Any]
) -> None:
    with pytest.raises(ScannerDisconnectedError) as excinfo:
        check(FakeScanner(clock, **options))

    assert str(excinfo.value) == DISAPPEARED


# --- cancel ------------------------------------------------------------------------------------


def test_cancel_during_the_hello_wait_stops_the_check_within_one_slice(clock: FakeClock) -> None:
    probe = CancelProbe(clock)
    scanner = FakeScanner(clock, swallow=None)
    scanner.on_read = lambda fake: probe.fire() if fake.reads >= 2 else None

    with pytest.raises(ScanCancelledError):
        check(scanner, cancel=probe.event)

    assert scanner.writes == [unstick.HELLO]
    assert probe.latency() <= CANCEL_LATENCY_S


def test_cancel_during_the_filler_stops_sending_within_one_slice(clock: FakeClock) -> None:
    probe = CancelProbe(clock)
    scanner = FakeScanner(clock, swallow=None)
    scanner.on_read = lambda fake: probe.fire() if fake.filler_bytes >= 3 * 64 else None

    with pytest.raises(ScanCancelledError):
        check_allowed(scanner, cancel=probe.event)

    assert scanner.filler_bytes == 3 * 64
    assert probe.latency() <= CANCEL_LATENCY_S


def test_cancel_while_the_scanner_refuses_an_out_is_noticed_within_one_slice(
    clock: FakeClock,
) -> None:
    probe = CancelProbe(clock)
    scanner = FakeScanner(clock, refuse_out_until_s=FOREVER_S)
    scanner.on_write = lambda fake: probe.fire() if fake.write_attempts >= 3 else None

    with pytest.raises(ScanCancelledError):
        check(scanner, cancel=probe.event)

    assert probe.latency() <= CANCEL_LATENCY_S


def test_cancel_while_stale_input_is_drained_stops_the_draining(clock: FakeClock) -> None:
    cancel = CancelProbe(clock)
    scanner = FakeScanner(clock, stale=tuple(b"stale" for _ in range(20)))
    scanner.on_read = lambda fake: cancel.fire() if fake.reads >= 3 else None

    with pytest.raises(ScanCancelledError):
        check(scanner, cancel=cancel.event)

    assert scanner.reads <= 5
    assert scanner.writes == []


def test_cancel_is_still_honoured_in_the_old_style_hook(clock: FakeClock) -> None:
    probe = CancelProbe(clock)
    scanner = FakeScanner(clock, swallow=None)
    scanner.on_read = cancel_after_reads(2, probe.event)

    with pytest.raises(ScanCancelledError):
        check(scanner, cancel=probe.event)


# --- telling the caller that it takes a while --------------------------------------------------


def test_a_check_that_takes_longer_than_2_seconds_says_so_once(clock: FakeClock) -> None:
    told: list[float] = []

    result = check(FakeScanner(clock, reply_after_s=5.0), on_slow=lambda: told.append(clock.now))

    assert result.outcome is Outcome.HEALTHY
    assert len(told) == 1
    assert 2.0 <= told[0] <= 2.6  # not at once, and not much later


@pytest.mark.parametrize("reply_after_s", [0.0, 1.0], ids=["at-once", "1-s"])
def test_a_quick_check_says_nothing(clock: FakeClock, reply_after_s: float) -> None:
    told: list[float] = []

    check(FakeScanner(clock, reply_after_s=reply_after_s), on_slow=lambda: told.append(clock.now))

    assert told == []


# --- what is logged ----------------------------------------------------------------------------


def test_a_freed_scanner_is_logged_at_info(
    clock: FakeClock, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER)

    check_allowed(FakeScanner(clock, swallow=STUCK_NEEDS_BYTES))

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

    check_allowed(FakeScanner(clock, swallow=STUCK_NEEDS_BYTES))

    text = "\n".join(r.getMessage() for r in caplog.records)
    assert text  # something was logged at debug
    for forbidden in ("parFAIL", "PARA", "x1c", "\\x", "b'", "0x20", "20 20"):
        assert forbidden not in text
