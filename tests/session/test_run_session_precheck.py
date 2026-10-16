"""``run_session`` checks the scanner before the scan and stops if it cannot be used."""

import threading
from dataclasses import replace
from typing import Any

import pytest

from fastfoto_linux.scanner import (
    ScanCancelledError,
    ScannerInUseError,
    ScannerStuckError,
    ScanTarget,
)
from fastfoto_linux.scanner import precheck as precheck_module
from fastfoto_linux.session import Stage, run_session
from tests.cli.fakes import DEVICE, FakeTransport
from tests.process_helpers import plain_sheet
from tests.session.conftest import Events, make_request, run


class Order:
    """What happened, in order: the check and the scan."""

    def __init__(self, transport: FakeTransport) -> None:
        self.events: list[str] = []
        self.checks: list[tuple[str, dict[str, Any]]] = []
        self.transport = transport
        transport.sheets = [plain_sheet(0)]

    def precheck(self, device: str, **options: Any) -> None:
        self.events.append("check")
        self.checks.append((device, options))

    def scan(self, job, **options):
        self.events.append("scan")
        return self.transport.run_scan(job, **options)


def failing(error: BaseException):
    def precheck(device: str, **options: Any) -> None:
        raise error

    return precheck


def test_the_scanner_is_checked_once_before_the_scan(out, transport) -> None:
    order = Order(transport)

    run_session(make_request(out), scan=order.scan, precheck=order.precheck)

    assert order.events == ["check", "scan"]


def test_the_check_is_given_the_device_and_the_cancel_event(out, transport) -> None:
    order = Order(transport)
    cancel = threading.Event()

    run_session(make_request(out), scan=order.scan, precheck=order.precheck, cancel=cancel)

    ((device, options),) = order.checks
    assert device == DEVICE
    assert options == {"cancel": cancel}


def test_the_stages_are_checking_scanning_processing_done(out, transport) -> None:
    order = Order(transport)
    events = Events()

    run_session(
        make_request(out),
        scan=order.scan,
        precheck=order.precheck,
        **events.callbacks(),
    )

    assert events.stages == [Stage.CHECKING, Stage.SCANNING, Stage.PROCESSING, Stage.DONE]


@pytest.mark.parametrize("error", [ScannerStuckError(), ScannerInUseError()], ids=["stuck", "busy"])
def test_a_scanner_that_fails_the_check_stops_the_session_before_the_scan(
    out, transport, error: Exception
) -> None:
    events = Events()

    session = run(make_request(out), transport, precheck=failing(error), **events.callbacks())

    assert session.error is error
    assert session.ok is False
    assert session.cancelled is False
    assert session.process is None
    assert session.pages_scanned == 0
    assert transport.jobs == []  # scanimage was never started
    assert events.stages == [Stage.CHECKING, Stage.DONE]


def test_a_cancel_during_the_check_is_a_cancelled_session(out, transport) -> None:
    cancelled = ScanCancelledError("scan cancelled while checking the scanner")

    session = run(make_request(out), transport, precheck=failing(cancelled))

    assert session.cancelled is True
    assert session.error is None
    assert transport.jobs == []


def test_an_interrupt_during_the_check_is_a_cancelled_session(out, transport) -> None:
    session = run(make_request(out), transport, precheck=failing(KeyboardInterrupt()))

    assert session.cancelled is True
    assert transport.jobs == []


def test_an_unexpected_error_in_the_check_comes_back_in_the_result(out, transport) -> None:
    boom = RuntimeError("the check blew up")

    session = run(make_request(out), transport, precheck=failing(boom))

    assert session.error is boom
    assert transport.jobs == []


# --- the check a session makes when none is handed in -----------------------------------------


@pytest.fixture
def default_check(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    """The real default, switched on, with the real check replaced by a recorder."""
    monkeypatch.delenv(precheck_module.SKIP_ENV_VAR, raising=False)
    calls: list[tuple[str, dict[str, Any]]] = []

    def record(device: str, **options: Any) -> None:
        calls.append((device, options))

    monkeypatch.setattr("fastfoto_linux.session.run.check_scanner", record)
    return calls


def test_a_usb_scanner_is_checked_by_default(out, transport, default_check) -> None:
    transport.sheets = [plain_sheet(0)]
    events = Events()

    run(make_request(out), transport, **events.callbacks())

    assert [device for device, _ in default_check] == [DEVICE]
    assert events.stages[:2] == [Stage.CHECKING, Stage.SCANNING]


def test_the_environment_can_switch_the_default_check_off(
    out, transport, default_check, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(precheck_module.SKIP_ENV_VAR, "1")
    transport.sheets = [plain_sheet(0)]
    events = Events()

    run(make_request(out), transport, **events.callbacks())

    assert default_check == []
    assert Stage.CHECKING not in events.stages


def test_a_network_scanner_is_not_checked_by_default(out, transport, default_check) -> None:
    transport.sheets = [plain_sheet(0)]
    request = replace(make_request(out), target=ScanTarget(device="epsonds:net:203.0.113.7"))
    events = Events()

    run(request, transport, **events.callbacks())

    assert default_check == []
    assert events.stages[0] is Stage.SCANNING
