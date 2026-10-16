"""``check_scanner``: when the check applies and what each way it can end does."""

import contextlib
import logging
import threading
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from fastfoto_linux.scanner import precheck, unclean, unstick
from fastfoto_linux.scanner.errors import (
    ScanCancelledError,
    ScannerError,
    ScannerInUseError,
    ScannerStuckError,
)
from fastfoto_linux.scanner.libusb import CheckUnavailableError, LibusbUnavailableError
from tests.unstick_fakes import STUCK_NEEDS_BYTES, FakeClock, FakeScanner, cancel_after_reads

DEVICE = "epsonds:libusb:001:004"
LOGGER = "fastfoto_linux.scanner"
NO_ANSWER = (
    "The scanner isn't answering. It may be busy with another device, or stuck \u2014 "
    "switch it off and on, then try again."
)


@pytest.fixture(autouse=True)
def check_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests are about the check, so it is on; libusb stays unloadable (see conftest)."""
    monkeypatch.delenv(precheck.SKIP_ENV_VAR, raising=False)


def opener_for(scanner: FakeScanner, asked: list[tuple[int, int]]) -> Callable[..., Any]:
    @contextlib.contextmanager
    def opener(bus: int, address: int) -> Iterator[FakeScanner]:
        asked.append((bus, address))
        yield scanner

    return opener


def failing_opener(error: Exception) -> Callable[..., Any]:
    @contextlib.contextmanager
    def opener(bus: int, address: int) -> Iterator[FakeScanner]:
        raise error
        yield  # pragma: no cover

    return opener


def run_check(
    scanner: FakeScanner, *, device: str = DEVICE, env: dict[str, str] | None = None, **options: Any
) -> list[tuple[int, int]]:
    asked: list[tuple[int, int]] = []
    precheck.check_scanner(
        device,
        env={} if env is None else env,
        opener=opener_for(scanner, asked),
        clock=scanner.clock,
        **options,
    )
    return asked


# --- which devices are checked -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("device", "expected"),
    [
        ("epsonds:libusb:001:004", (1, 4)),
        ("epsonds:libusb:12:3", (12, 3)),
        ("epsonds:libusb:999:999", (999, 999)),
        ("epsonds:libusb:0001:004", None),
        ("epsonds:libusb:001:0004", None),
        ("epsonds:libusb:12345:1", None),
        ("epsonds:libusb:" + "9" * 5000 + ":1", None),
        ("epsonds:net:203.0.113.7", None),
        ("epsonds", None),
        ("epsonds:libusb:001", None),
        ("epsonds:libusb:001:004:5", None),
        ("epsonds:libusb:a:b", None),
        ("other:libusb:001:004", None),
        ("", None),
    ],
)
def test_the_bus_and_address_come_from_a_usb_sane_name(
    device: str, expected: tuple[int, int] | None
) -> None:
    assert precheck.usb_address(device) == expected


def test_a_usb_scanner_is_checked() -> None:
    assert precheck.precheck_applies(DEVICE, {}) is True


def test_a_network_scanner_is_never_checked() -> None:
    assert precheck.precheck_applies("epsonds:net:203.0.113.7", {}) is False


def test_the_environment_can_switch_the_check_off() -> None:
    assert precheck.precheck_applies(DEVICE, {precheck.SKIP_ENV_VAR: "1"}) is False
    assert precheck.precheck_applies(DEVICE, {precheck.SKIP_ENV_VAR: "0"}) is True


def test_a_network_scanner_is_not_opened() -> None:
    def never(*args: Any) -> Any:
        raise AssertionError("a network scanner must not be opened over USB")

    precheck.check_scanner("epsonds:net:203.0.113.7", env={}, opener=never)


def test_switched_off_the_scanner_is_not_opened() -> None:
    def never(*args: Any) -> Any:
        raise AssertionError("FF680W_NO_PRECHECK=1 must skip the check")

    precheck.check_scanner(DEVICE, env={precheck.SKIP_ENV_VAR: "1"}, opener=never)


def test_the_environment_defaults_to_the_processs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(precheck.SKIP_ENV_VAR, "1")

    def never(*args: Any) -> Any:
        raise AssertionError("FF680W_NO_PRECHECK=1 must skip the check")

    precheck.check_scanner(DEVICE, opener=never)


# --- how the check ends ------------------------------------------------------------------------


def test_a_healthy_scanner_is_opened_by_its_address_and_asked_hello() -> None:
    scanner = FakeScanner(FakeClock())

    asked = run_check(scanner)

    assert asked == [(1, 4)]
    assert scanner.writes == [unstick.HELLO, unstick.FIN]


def test_a_stuck_scanner_is_freed_and_the_scan_may_go_on(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER)
    unclean.mark(1, 4)  # our own last scan here ended badly
    scanner = FakeScanner(FakeClock(), swallow=STUCK_NEEDS_BYTES)

    run_check(scanner)

    assert any("freed it" in r.getMessage() for r in caplog.records)


def test_a_scanner_that_cannot_be_freed_stops_the_scan() -> None:
    unclean.mark(1, 4)

    with pytest.raises(ScannerStuckError):
        run_check(FakeScanner(FakeClock(), swallow=None))


def test_a_scanner_held_by_another_program_stops_the_scan() -> None:
    with pytest.raises(ScannerInUseError, match="in use by another program"):
        precheck.check_scanner(
            DEVICE, env={}, opener=failing_opener(ScannerInUseError()), clock=FakeClock()
        )


def test_the_errors_are_scanner_errors_so_the_session_calls_them_that() -> None:
    assert issubclass(ScannerStuckError, ScannerError)
    assert issubclass(ScannerInUseError, ScannerError)


def test_missing_libusb_goes_on_without_the_check_and_says_so_at_debug(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER)

    precheck.check_scanner(DEVICE, env={}, opener=failing_opener(LibusbUnavailableError("no")))

    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []
    assert any("libusb" in r.getMessage() for r in caplog.records)


def test_a_scanner_that_cannot_be_opened_goes_on_without_the_check(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER)

    precheck.check_scanner(
        DEVICE, env={}, opener=failing_opener(CheckUnavailableError("permission denied"))
    )

    assert any("without the check" in r.getMessage() for r in caplog.records)


def test_the_default_opener_finds_no_libusb_in_the_tests_and_the_check_goes_on() -> None:
    """The whole chain with nothing faked: conftest keeps libusb out of reach."""
    precheck.check_scanner(DEVICE, env={})


def test_the_default_opener_is_looked_up_when_the_check_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scanner = FakeScanner(FakeClock())
    asked: list[tuple[int, int]] = []
    monkeypatch.setattr(precheck, "open_scanner", opener_for(scanner, asked))

    precheck.check_scanner(DEVICE, env={}, clock=scanner.clock)

    assert asked == [(1, 4)]


# --- filler only with evidence that the stuck session is ours ----------------------------------


def test_a_silent_scanner_without_a_note_is_sent_nothing_beyond_the_hello(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Silence may be the scanner's session with another device over Wi-Fi."""
    caplog.set_level(logging.INFO, logger=LOGGER)
    scanner = FakeScanner(FakeClock(), swallow=STUCK_NEEDS_BYTES)

    with pytest.raises(ScannerStuckError) as excinfo:
        run_check(scanner)

    assert str(excinfo.value) == NO_ANSWER
    assert scanner.writes == [unstick.HELLO]
    infos = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert any(precheck.FORCE_ENV_VAR in message for message in infos)  # how to override


def test_a_note_for_this_address_lets_the_stuck_scanner_be_freed_and_is_then_cleared() -> None:
    unclean.mark(1, 4)
    scanner = FakeScanner(FakeClock(), swallow=STUCK_NEEDS_BYTES)

    run_check(scanner)

    assert scanner.filler_bytes > 0
    assert not unclean.marker_path().exists()


def test_a_note_for_another_address_is_no_evidence() -> None:
    unclean.mark(1, 5)
    scanner = FakeScanner(FakeClock(), swallow=STUCK_NEEDS_BYTES)

    with pytest.raises(ScannerStuckError, match="busy with another device"):
        run_check(scanner)

    assert scanner.writes == [unstick.HELLO]
    assert unclean.is_marked(1, 5)  # it was not ours to clear


def test_the_environment_can_allow_filler_without_a_note_as_a_last_resort() -> None:
    scanner = FakeScanner(FakeClock(), swallow=STUCK_NEEDS_BYTES)

    run_check(scanner, env={precheck.FORCE_ENV_VAR: "1"})

    assert scanner.filler_bytes > 0


@pytest.mark.parametrize("value", ["0", "", "yes", "true"])
def test_only_force_unstick_equal_to_1_allows_it(value: str) -> None:
    scanner = FakeScanner(FakeClock(), swallow=STUCK_NEEDS_BYTES)

    with pytest.raises(ScannerStuckError):
        run_check(scanner, env={precheck.FORCE_ENV_VAR: value})

    assert scanner.filler_bytes == 0


def test_a_scanner_that_answers_clears_the_note() -> None:
    unclean.mark(1, 4)

    run_check(FakeScanner(FakeClock()))

    assert not unclean.marker_path().exists()


def test_a_scanner_that_cannot_be_freed_keeps_the_note() -> None:
    unclean.mark(1, 4)

    with pytest.raises(ScannerStuckError):
        run_check(FakeScanner(FakeClock(), swallow=None))

    assert unclean.is_marked(1, 4)


def test_a_cancelled_check_keeps_the_note() -> None:
    unclean.mark(1, 4)
    cancel = threading.Event()
    scanner = FakeScanner(FakeClock(), swallow=None)
    scanner.on_read = cancel_after_reads(3, cancel)

    with pytest.raises(ScanCancelledError):
        run_check(scanner, cancel=cancel)

    assert unclean.is_marked(1, 4)


def test_a_network_scanner_leaves_the_note_alone() -> None:
    unclean.mark(1, 4)

    precheck.check_scanner("epsonds:net:203.0.113.7", env={})

    assert unclean.is_marked(1, 4)


# --- telling the caller it takes a while --------------------------------------------------------


def test_a_slow_answer_is_passed_on_to_the_caller_once() -> None:
    told: list[int] = []
    scanner = FakeScanner(FakeClock(), reply_after_s=4.0)

    run_check(scanner, on_slow=lambda: told.append(1))

    assert told == [1]


def test_a_quick_answer_tells_the_caller_nothing() -> None:
    told: list[int] = []

    run_check(FakeScanner(FakeClock()), on_slow=lambda: told.append(1))

    assert told == []


# --- cancel ------------------------------------------------------------------------------------


def test_a_cancel_that_is_already_set_opens_nothing() -> None:
    cancel = threading.Event()
    cancel.set()

    def never(*args: Any) -> Any:
        raise AssertionError("a cancelled scan must not touch the scanner")

    with pytest.raises(ScanCancelledError):
        precheck.check_scanner(DEVICE, env={}, cancel=cancel, opener=never)


def test_a_cancel_during_the_check_is_passed_on() -> None:
    cancel = threading.Event()
    scanner = FakeScanner(FakeClock(), swallow=None)
    scanner.on_read = cancel_after_reads(2, cancel)

    with pytest.raises(ScanCancelledError):
        run_check(scanner, cancel=cancel)
