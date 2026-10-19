"""Power operations share the scanner worker and report after ownership is released."""

import threading
from typing import Any

import pytest

from fastfoto_linux.gui.power import PowerResult, PowerTools
from fastfoto_linux.gui.worker import Worker, WorkerBusyError
from fastfoto_linux.scanner.power import PowerChanges
from tests.gui.helpers import RecordingSink
from tests.gui.power_helpers import SCANNER, snapshot

WAIT = 5.0


class PowerSink(RecordingSink):
    def on_power(self, result: PowerResult) -> None:
        self._add("power", result)
        self.finished.set()


def make_worker(sink: PowerSink, **tools: Any) -> Worker:
    worker = Worker(sink, discover=lambda: pytest.fail("ordinary discovery must not run"))
    worker._power_tools = PowerTools(**tools)
    return worker


def test_read_and_apply_use_the_same_worker_thread_and_bound_scanner() -> None:
    sink = PowerSink()
    calls = []

    def read(scanner: Any = None, *, cancel: threading.Event) -> Any:
        calls.append(("read", scanner, cancel))
        return snapshot()

    def apply(scanner: Any, changes: PowerChanges, *, cancel: threading.Event) -> Any:
        calls.append(("apply", scanner, changes, cancel))
        return snapshot(sleep_minutes=20)

    worker = make_worker(sink, read=read, apply=apply)
    assert calls == []
    worker.read_power()
    worker.join(WAIT)
    worker.apply_power(SCANNER, PowerChanges(sleep_minutes=20))
    worker.join(WAIT)
    assert [call[0] for call in calls] == ["read", "apply"]
    assert calls[0][1] is None
    assert calls[1][1:3] == (SCANNER, PowerChanges(sleep_minutes=20))
    assert all(isinstance(call[-1], threading.Event) for call in calls)
    assert sink.names == ["power", "power"]
    assert sink.events[-1][1].snapshot.sleep_minutes == 20
    assert all(thread != threading.get_ident() for thread in sink.threads)
    assert not worker.busy


def test_power_read_serializes_with_discovery_and_cancel_uses_shared_event() -> None:
    sink = PowerSink()
    entered = threading.Event()

    def read(scanner: Any = None, *, cancel: threading.Event) -> Any:
        entered.set()
        assert cancel.wait(WAIT)
        return snapshot()

    worker = make_worker(sink, read=read)
    worker.read_power()
    try:
        assert entered.wait(WAIT)
        with pytest.raises(WorkerBusyError):
            worker.check()
        with pytest.raises(WorkerBusyError):
            worker.read_power()
        with pytest.raises(WorkerBusyError):
            worker.apply_power(SCANNER, PowerChanges(sleep_minutes=20))
    finally:
        worker.cancel()
        worker.join(WAIT)
    assert not worker.alive


def test_power_failure_is_reported_to_settings_and_not_scan_error_sink() -> None:
    sink = PowerSink()
    error = RuntimeError("write outcome uncertain; read settings again")

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise error

    worker = make_worker(sink, apply=fail)
    worker.apply_power(SCANNER, PowerChanges(sleep_minutes=20))
    worker.join(WAIT)
    assert sink.names == ["power"]
    assert sink.events[0][1].error is error
    assert not worker.busy
