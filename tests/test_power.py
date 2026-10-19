"""Actual capability/current reads and explicitly requested, verified timer changes."""

import dataclasses
import threading

import pytest

from fastfoto_linux.scanner import power
from fastfoto_linux.scanner.errors import ScanCancelledError, ScannerInUseError
from fastfoto_linux.scanner.unstick import TransportError
from tests.power_helpers import (
    CAPS,
    CURRENT,
    TARGET,
    ScriptedUsb,
    apply_usb,
    frame,
    install_usb,
    read_usb,
)


def test_read_uses_maintenance_only_and_returns_actual_capabilities(monkeypatch):
    usb = read_usb()
    install_usb(monkeypatch, usb)
    snapshot = power.read_power_settings()
    assert snapshot.scanner == TARGET
    assert (snapshot.sleep_minutes, snapshot.power_off_minutes) == (10, 60)
    assert snapshot.sleep_capability == power.TimerCapability(minimum=1, maximum=240)
    assert snapshot.power_off_capability == power.TimerCapability(
        values=(0, 30, 60, 120, 240, 480, 720)
    )
    assert usb.stream == b"\x1cZCAPAx0000000RESAx0000000FIN x0000000"
    assert usb.released
    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.sleep_minutes = 5


def test_apply_reloads_validates_acks_and_reads_back(monkeypatch):
    usb = apply_usb()
    install_usb(monkeypatch, usb)
    answer = power.apply_power_settings(TARGET, power.PowerChanges(30, 0))
    assert (answer.sleep_minutes, answer.power_off_minutes) == (30, 0)
    assert (
        usb.stream
        == b"\x1cZCAPAx0000000RESAx0000000PARAx0000010#SAVd030#POFd000RESAx0000000FIN x0000000"
    )
    assert usb.released


def test_empty_changes_and_unchanged_values_never_send_para(monkeypatch):
    for changes in (power.PowerChanges(), power.PowerChanges(10, 60)):
        usb = read_usb()
        install_usb(monkeypatch, usb)
        assert power.apply_power_settings(TARGET, changes).sleep_minutes == 10
        assert b"PARA" not in usb.stream


@pytest.mark.parametrize(
    "changes",
    [
        power.PowerChanges(0),
        power.PowerChanges(241),
        power.PowerChanges(power_off_minutes=45),
        power.PowerChanges(True),
    ],
)
def test_invalid_changes_fail_against_fresh_caps_before_para(monkeypatch, changes):
    usb = read_usb()
    install_usb(monkeypatch, usb)
    with pytest.raises(power.PowerSettingsError):
        power.apply_power_settings(TARGET, changes)
    assert b"PARA" not in usb.stream
    assert usb.stream.endswith(b"FIN x0000000")
    assert usb.released


def test_busy_interface_is_respected_without_any_commands(monkeypatch):
    def busy(*_args):
        raise ScannerInUseError

    monkeypatch.setattr(power, "open_scanner", busy)
    with pytest.raises(ScannerInUseError):
        power.read_power_settings(TARGET)


@pytest.mark.parametrize("targets", [(), (TARGET, TARGET)])
def test_discovery_does_not_guess_scanner(monkeypatch, targets):
    monkeypatch.setattr(power, "find_usb_scanners", lambda: targets)
    monkeypatch.setattr(power, "open_scanner", lambda *_a: pytest.fail("must not open USB"))
    with pytest.raises(power.PowerSettingsError):
        power.read_power_settings()


def test_cancel_before_open_does_no_usb(monkeypatch):
    cancelled = threading.Event()
    cancelled.set()
    monkeypatch.setattr(power, "open_scanner", lambda *_a: pytest.fail("must not open USB"))
    with pytest.raises(ScanCancelledError):
        power.read_power_settings(TARGET, cancel=cancelled)


@pytest.mark.parametrize("ack", [b"\x15", b"B", TransportError("no ACK")])
def test_no_ack_never_finishes_someone_elses_session(monkeypatch, ack):
    usb = ScriptedUsb(ack)
    install_usb(monkeypatch, usb)
    with pytest.raises(power.PowerSettingsError):
        power.read_power_settings(TARGET)
    assert usb.stream == b"\x1cZ"
    assert usb.released


def test_mismatch_carries_fresh_snapshot(monkeypatch):
    usb = apply_usb(updated=CURRENT)
    install_usb(monkeypatch, usb)
    with pytest.raises(power.PowerReadbackError) as error:
        power.apply_power_settings(TARGET, power.PowerChanges(30, 0))
    assert error.value.snapshot.power_off_minutes == 60
    assert usb.stream.endswith(b"FIN x0000000")
    assert usb.released


@pytest.mark.parametrize("status", [b"", b"#parFAIL", b"#parLOST"])
def test_parameter_success_is_required_and_never_retried(monkeypatch, status):
    usb = apply_usb(status=status)
    install_usb(monkeypatch, usb)
    with pytest.raises(power.PowerSettingsError):
        power.apply_power_settings(TARGET, power.PowerChanges(30, 0))
    assert usb.stream.count(b"PARA") == 1
    assert usb.released


@pytest.mark.parametrize("failure_at", [3, 4])
def test_possible_write_without_verified_result_is_uncertain(monkeypatch, failure_at):
    replies = [b"\x06", frame(b"CAPA", CAPS), frame(b"RESA", CURRENT)]
    if failure_at == 4:
        replies.append(frame(b"PARA", status=b"#parOK  "))
    replies.extend([TransportError("reply unavailable"), frame(b"FIN ")])
    usb = ScriptedUsb(*replies)
    install_usb(monkeypatch, usb)
    with pytest.raises(power.PowerWriteUncertainError):
        power.apply_power_settings(TARGET, power.PowerChanges(30, 0))
    assert usb.stream.count(b"PARA") == 1
    assert usb.released


def test_cleanup_failure_is_visible_after_successful_read(monkeypatch):
    usb = ScriptedUsb(
        b"\x06", frame(b"CAPA", CAPS), frame(b"RESA", CURRENT), TransportError("FIN failed")
    )
    install_usb(monkeypatch, usb)
    with pytest.raises(power.PowerCleanupError):
        power.read_power_settings(TARGET)
    assert usb.released


def test_original_error_survives_cleanup_failure(monkeypatch):
    usb = ScriptedUsb(
        b"\x06", frame(b"CAPA", b"#SAVRANGd240d001#---"), TransportError("FIN failed")
    )
    install_usb(monkeypatch, usb)
    with pytest.raises(power.PowerSettingsError) as error:
        power.read_power_settings(TARGET)
    assert not isinstance(error.value, power.PowerCleanupError)
    assert usb.released


def test_failure_while_sending_parameter_payload_is_uncertain(monkeypatch):
    usb = apply_usb()
    usb.write_error_at = 5  # FS-Z, CAPA, RESA, PARA header, PARA payload
    install_usb(monkeypatch, usb)
    with pytest.raises(power.PowerWriteUncertainError):
        power.apply_power_settings(TARGET, power.PowerChanges(30, 0))
    assert usb.stream.count(b"PARA") == 1
    assert usb.released


def test_missing_current_blocks_requested_write(monkeypatch):
    usb = ScriptedUsb(b"\x06", frame(b"CAPA", CAPS), frame(b"RESA", b"#---"), frame(b"FIN "))
    install_usb(monkeypatch, usb)
    with pytest.raises(power.PowerSettingsError):
        power.apply_power_settings(TARGET, power.PowerChanges(30))
    assert b"PARA" not in usb.stream
    assert usb.released


def test_cancellation_after_ack_cleans_up_owned_session(monkeypatch):
    cancelled = threading.Event()
    usb = read_usb()
    original_read = usb.read

    def read(size, timeout_ms):
        answer = original_read(size, timeout_ms)
        cancelled.set()
        return answer

    monkeypatch.setattr(usb, "read", read)
    install_usb(monkeypatch, usb)
    with pytest.raises(ScanCancelledError):
        power.read_power_settings(TARGET, cancel=cancelled)
    assert usb.stream == b"\x1cZFIN x0000000"
    assert usb.released
