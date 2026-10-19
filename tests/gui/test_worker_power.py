"""Power operations share the scanner worker and report after ownership is released."""

import subprocess
import sys
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from fastfoto_linux.gui.docform import DocumentForm
from fastfoto_linux.gui.form import ScanForm
from fastfoto_linux.gui.power import PowerResult, PowerTools
from fastfoto_linux.gui.worker import Worker, WorkerBusyError
from fastfoto_linux.scanner import recovery
from fastfoto_linux.scanner.power import (
    PowerChanges,
    PowerSettingsError,
    PowerWriteUncertainError,
)
from tests.gui.helpers import RecordingSink
from tests.gui.power_helpers import OTHER_SCANNER, SCANNER, snapshot

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


def unsafe_worker() -> tuple[Worker, PowerSink, list[object]]:
    sink = PowerSink()
    calls: list[object] = []

    def fail(*args: Any, **kwargs: Any) -> Any:
        calls.append("write")
        raise PowerWriteUncertainError(
            "partial PARA; turn scanner off and on",
            scanner=SCANNER,
            reconnect_required=True,
        )

    worker = make_worker(sink, apply=fail)
    worker.apply_power(SCANNER, PowerChanges(sleep_minutes=20))
    worker.join(WAIT)
    return worker, sink, calls


def test_desynchronized_power_write_blocks_every_scanner_command_before_io() -> None:
    worker, sink, calls = unsafe_worker()
    assert worker.reconnect_required
    for operation in (
        worker.check,
        worker.read_power,
        lambda: worker.apply_power(SCANNER, PowerChanges(sleep_minutes=21)),
        lambda: worker.scan(ScanForm()),
        lambda: worker.scan_documents(DocumentForm(), "", ocr_available=False),
    ):
        with pytest.raises(PowerSettingsError, match=r"[Tt]urn.*off.*on"):
            operation()
    worker.cancel()
    worker.join(WAIT)
    assert worker.reconnect_required
    assert sink.names == ["power"]
    assert calls == ["write"]


@pytest.mark.parametrize("visible", [(SCANNER,), (), (OTHER_SCANNER,)])
def test_metadata_check_without_the_restarted_scanner_keeps_device_commands_blocked(
    visible: tuple[Any, ...],
) -> None:
    worker, sink, calls = unsafe_worker()
    metadata_reads = []

    def discover() -> tuple[Any, ...]:
        metadata_reads.append(True)
        return visible

    worker._power_tools = PowerTools(discover=discover)
    worker.check_power_connection()
    worker.join(WAIT)
    assert worker.reconnect_required
    assert metadata_reads == [True]
    assert calls == ["write"]
    assert sink.events[-1][1].error.reconnect_required


def test_only_new_enumeration_on_the_same_physical_usb_path_clears_the_latch() -> None:
    worker, sink, calls = unsafe_worker()
    restarted = replace(SCANNER, device=SCANNER.device + 10)
    worker._power_tools = PowerTools(discover=lambda: (restarted, OTHER_SCANNER))
    worker.check_power_connection()
    worker.join(WAIT)
    assert not worker.reconnect_required
    assert sink.events[-1][1].recovered_scanner == restarted
    assert calls == ["write"]


def test_device_quarantine_does_not_prevent_jobs_that_only_process_existing_images() -> None:
    worker, _, _ = unsafe_worker()
    completed = threading.Event()

    def local_job(cancel: threading.Event) -> Any:
        return completed.set

    worker._start(local_job)
    worker.join(WAIT)
    assert completed.is_set()
    assert worker.reconnect_required


def test_aligned_failure_does_not_require_physical_reconnection() -> None:
    sink = PowerSink()

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise PowerWriteUncertainError("read back before applying again", scanner=SCANNER)

    worker = make_worker(sink, apply=fail)
    worker.apply_power(SCANNER, PowerChanges(sleep_minutes=20))
    worker.join(WAIT)
    assert not worker.reconnect_required
    assert sink.events[-1][1].error.reconnect_required is False


def test_power_job_keeps_the_process_alive_until_cleanup_finishes(tmp_path: Path) -> None:
    marker = tmp_path / "power-cleanup.txt"
    done = subprocess.run(
        [sys.executable, "-m", "tests.gui.power_lifetime_app", str(marker)],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert marker.read_text() == "cleanup finished"


def test_new_worker_loads_persisted_guard_before_discovery_or_scanner_io() -> None:
    recovery.begin(SCANNER)
    sink = PowerSink()
    worker = make_worker(sink)
    assert worker.reconnect_required
    with pytest.raises(PowerSettingsError):
        worker.check()
    with pytest.raises(PowerSettingsError):
        worker.read_power()
    assert sink.events == []
    assert recovery.pending_targets() == (SCANNER,)


def test_metadata_recovery_clears_durable_marker_and_a_new_worker_stays_safe() -> None:
    recovery.begin(SCANNER)
    worker = make_worker(PowerSink())
    restarted = replace(SCANNER, device=SCANNER.device + 10)
    worker._power_tools = PowerTools(discover=lambda: (restarted,))
    worker.check_power_connection()
    worker.join(WAIT)
    assert recovery.pending_targets() == ()
    assert not worker.reconnect_required
    assert not make_worker(PowerSink()).reconnect_required


def test_pending_marker_created_by_another_process_is_checked_before_each_device_job() -> None:
    worker = make_worker(PowerSink())
    assert not worker.reconnect_required
    recovery.begin(SCANNER)
    with pytest.raises(PowerSettingsError):
        worker.check()
    assert worker.reconnect_required


def test_corrupt_persistent_state_preserves_the_actionable_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def corrupt() -> tuple[Any, ...]:
        raise PowerSettingsError(
            "Unreadable recovery journal: turn scanner off, then repair the state file",
            reconnect_required=True,
        )

    monkeypatch.setattr(recovery, "pending_targets", corrupt)
    worker = make_worker(PowerSink())
    assert worker.reconnect_required
    assert "repair the state file" in worker.power_recovery_message
    with pytest.raises(PowerSettingsError, match="repair the state file"):
        worker.check()
