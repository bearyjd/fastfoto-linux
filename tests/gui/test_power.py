"""Drafts must follow actual scanner replies and must never write on their own."""

from typing import Any

import pytest

from fastfoto_linux.gui.power import PowerResult, PowerSettings
from fastfoto_linux.gui.state import ActionBlockedError
from fastfoto_linux.scanner import ScannerNotFoundError
from fastfoto_linux.scanner.power import (
    PowerChanges,
    PowerReadbackError,
    PowerWriteUncertainError,
    TimerCapability,
)
from tests.gui.power_helpers import OTHER_SCANNER, SCANNER, PowerWorker, snapshot


def model(worker: PowerWorker | None = None) -> tuple[PowerSettings, PowerWorker]:
    worker = worker or PowerWorker()
    settings = PowerSettings(worker, busy=lambda: worker.busy, changed=lambda: None)
    return settings, worker


def loaded() -> tuple[PowerSettings, PowerWorker]:
    settings, worker = model()
    settings.read()
    settings.complete(PowerResult(snapshot=snapshot()))
    return settings, worker


def test_opening_settings_does_no_io_and_has_no_invented_current_values() -> None:
    settings, worker = model()
    assert worker.calls == []
    assert settings.snapshot is None
    assert settings.drafts == {}
    assert settings.can_read
    assert not settings.can_apply


def test_explicit_read_binds_actual_values_and_refresh_to_the_same_scanner() -> None:
    settings, worker = loaded()
    assert settings.snapshot == snapshot()
    assert settings.target == SCANNER
    assert settings.drafts == {"sleep_minutes": 17, "power_off_minutes": 60}
    assert not settings.can_apply
    settings.read()
    assert worker.calls == [("read", None), ("read", SCANNER)]


def test_only_edited_values_are_applied_then_verified_values_replace_drafts() -> None:
    settings, worker = loaded()
    settings.set_value("sleep_minutes", 22)
    assert settings.can_apply
    settings.apply()
    assert worker.calls[-1] == ("apply", (SCANNER, PowerChanges(sleep_minutes=22)))
    assert settings.pending
    assert not settings.can_read
    settings.complete(PowerResult(snapshot=snapshot(sleep_minutes=22)))
    assert settings.snapshot.sleep_minutes == 22
    assert not settings.can_apply
    assert "verified" in settings.message.lower()


def test_reverting_the_edit_or_applying_an_empty_draft_never_writes() -> None:
    settings, worker = loaded()
    settings.set_value("sleep_minutes", 20)
    settings.set_value("sleep_minutes", 17)
    assert not settings.can_apply
    with pytest.raises(ActionBlockedError):
        settings.apply()
    assert [name for name, _ in worker.calls] == ["read"]


@pytest.mark.parametrize("name,value", [("sleep_minutes", 0), ("power_off_minutes", 45)])
def test_values_not_advertised_by_the_device_cannot_be_applied(name: str, value: int) -> None:
    settings, worker = loaded()
    settings.set_value(name, value)
    assert not settings.can_apply
    with pytest.raises(ActionBlockedError):
        settings.apply()
    assert len(worker.calls) == 1


def test_zero_is_allowed_only_when_that_timer_advertises_it() -> None:
    settings, _ = loaded()
    settings.set_value("power_off_minutes", 0)
    assert settings.can_apply
    settings.read()
    settings.complete(
        PowerResult(snapshot=snapshot(power_off_capability=TimerCapability(values=(30, 60))))
    )
    settings.set_value("power_off_minutes", 0)
    assert not settings.can_apply


def test_unsupported_or_unknown_current_timer_is_not_editable() -> None:
    settings, worker = model()
    settings.read()
    settings.complete(PowerResult(snapshot=snapshot(sleep_capability=None, power_off_minutes=None)))
    assert not settings.can_apply
    with pytest.raises(ActionBlockedError):
        settings.set_value("sleep_minutes", 10)
    with pytest.raises(ActionBlockedError):
        settings.set_value("power_off_minutes", 0)
    assert len(worker.calls) == 1


def test_conflicting_worker_job_disables_and_refuses_read_apply_and_edits() -> None:
    settings, worker = loaded()
    settings.set_value("sleep_minutes", 25)
    worker.busy = True
    assert not settings.can_read
    assert not settings.can_apply
    for action in (settings.read, settings.apply, lambda: settings.set_value("sleep_minutes", 26)):
        with pytest.raises(ActionBlockedError):
            action()
    assert len(worker.calls) == 1


def test_selection_change_clears_current_values_drafts_and_late_reply() -> None:
    settings, worker = loaded()
    settings.set_value("sleep_minutes", 20)
    settings.read()
    settings.select(OTHER_SCANNER)
    settings.complete(PowerResult(snapshot=snapshot()))
    assert settings.target == OTHER_SCANNER
    assert settings.snapshot is None
    assert settings.drafts == {}
    assert not settings.can_apply
    settings.read()
    assert worker.calls[-1] == ("read", OTHER_SCANNER)


@pytest.mark.parametrize(
    "error", [ScannerNotFoundError("disconnected"), RuntimeError("uncertain write")]
)
def test_failed_job_forgets_stale_current_values_and_requires_a_read(error: Exception) -> None:
    settings, worker = loaded()
    settings.set_value("sleep_minutes", 20)
    settings.apply()
    settings.complete(PowerResult(error=error))
    assert settings.snapshot is None
    assert not settings.can_apply
    assert settings.can_read
    assert str(error) in settings.message
    assert len(worker.calls) == 2


def test_a_reply_for_a_different_scanner_is_never_accepted() -> None:
    settings, _ = loaded()
    settings.read()
    settings.complete(PowerResult(snapshot=snapshot(scanner=OTHER_SCANNER)))
    assert settings.snapshot is None
    assert not settings.can_apply
    assert "scanner" in settings.message.lower()


def test_start_failure_is_visible_and_does_not_leave_a_pending_job() -> None:
    class RefusingWorker(PowerWorker):
        def read_power(self, scanner: Any = None) -> None:
            raise RuntimeError("busy")

    settings, _ = model(RefusingWorker())
    settings.read()
    assert not settings.pending
    assert "busy" in settings.message


def test_readback_mismatch_shows_returned_current_values_but_requires_refresh() -> None:
    settings, worker = loaded()
    settings.set_value("sleep_minutes", 20)
    settings.apply()
    actual = snapshot(sleep_minutes=21)
    settings.complete(PowerResult(error=PowerReadbackError("different settings returned", actual)))
    assert settings.snapshot == actual
    assert settings.drafts == {}
    assert settings.can_read
    assert not settings.can_apply
    assert len(worker.calls) == 2


def test_disconnect_forgets_bound_target_so_a_new_read_can_discover_again() -> None:
    settings, worker = loaded()
    settings.read()
    settings.complete(PowerResult(error=ScannerNotFoundError("disconnected")))
    assert settings.target is None
    settings.read()
    assert worker.calls[-1] == ("read", None)


def test_late_unsafe_report_survives_selection_change_and_blocks_new_reads() -> None:
    settings, worker = loaded()
    settings.read()
    settings.select(OTHER_SCANNER)
    settings.complete(
        PowerResult(
            error=PowerWriteUncertainError("partial PARA", scanner=SCANNER, reconnect_required=True)
        )
    )
    assert settings.reconnect_required
    assert not settings.can_read
    assert not settings.can_apply
    settings.select(None)
    assert settings.reconnect_required
    assert "off and on" in settings.message.lower()
    assert len(worker.calls) == 2
