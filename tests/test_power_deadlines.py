"""Absolute deadlines and desynchronization prevent further unsafe device commands."""

import threading

import pytest

from fastfoto_linux.scanner import maintenance, power
from fastfoto_linux.scanner.unstick import TransportError
from tests.power_helpers import CAPS, CURRENT, TARGET, ScriptedUsb, apply_usb, frame, install_usb


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def install_clock(monkeypatch, clock):
    monkeypatch.setattr(maintenance, "_clock", clock.monotonic)
    monkeypatch.setattr(maintenance, "_sleep", clock.sleep)
    monkeypatch.setattr(maintenance, "OPERATION_TIMEOUT_S", 1.0)
    monkeypatch.setattr(maintenance, "CLEANUP_TIMEOUT_S", 0.5)


@pytest.mark.parametrize("direction", ["read", "write"])
def test_zero_progress_stops_at_deadline_without_spin_or_fin(monkeypatch, direction):
    clock = Clock()
    install_clock(monkeypatch, clock)
    usb = ScriptedUsb()
    calls = []

    def stalled(*args):
        calls.append(args)
        clock.now += args[-1] / 1000
        return b"" if direction == "read" else 0

    monkeypatch.setattr(usb, direction, stalled)
    install_usb(monkeypatch, usb)
    with pytest.raises(power.PowerSettingsError) as error:
        power.read_power_settings(TARGET)
    assert 1 <= clock.now <= 1.5
    assert len(calls) <= 10
    assert error.value.reconnect_required
    assert error.value.scanner == TARGET
    assert b"FIN " not in usb.stream
    assert usb.released


def test_partial_progress_does_not_restart_absolute_operation_deadline(monkeypatch):
    clock = Clock()
    install_clock(monkeypatch, clock)
    usb = ScriptedUsb(b"\x06", frame(b"CAPA", CAPS), fragment=1)
    original = usb.read
    calls = []

    def slow_read(size, timeout_ms):
        calls.append(timeout_ms)
        clock.now += 0.2
        return original(size, timeout_ms)

    monkeypatch.setattr(usb, "read", slow_read)
    install_usb(monkeypatch, usb)
    with pytest.raises(power.PowerSettingsError) as error:
        power.read_power_settings(TARGET)
    assert 1 <= clock.now <= 1.4
    assert len(calls) <= 7
    assert error.value.reconnect_required
    assert b"FIN " not in usb.stream
    assert usb.released


def test_cancel_after_partial_parameter_out_never_appends_fin(monkeypatch):
    cancel = threading.Event()
    usb = apply_usb()
    original = usb.write

    def partial_cancel(data, timeout_ms):
        if data.startswith(b"#SAV"):
            usb.sent.append(data[:3])
            cancel.set()
            return 3
        return original(data, timeout_ms)

    monkeypatch.setattr(usb, "write", partial_cancel)
    install_usb(monkeypatch, usb)
    with pytest.raises(power.PowerWriteUncertainError) as error:
        power.apply_power_settings(TARGET, power.PowerChanges(30, 0), cancel=cancel)
    assert error.value.reconnect_required
    assert error.value.scanner == TARGET
    assert usb.stream.endswith(b"#SA")
    assert b"FIN " not in usb.stream
    assert usb.released


@pytest.mark.parametrize(
    "reply",
    [
        b"CAPAxFFFFFFF#---".ljust(64, b"\x00"),
        b"CAPAx00000Q0#---".ljust(64, b"\x00"),
        b"CAPAx0000004#---".ljust(64, b"\x00") + b"ab",
        b"CAPAx00",
    ],
)
def test_incomplete_or_unclassifiable_response_only_releases_usb(monkeypatch, reply):
    usb = ScriptedUsb(b"\x06", reply, TransportError("broken stream"))
    install_usb(monkeypatch, usb)
    with pytest.raises(power.PowerSettingsError) as error:
        power.read_power_settings(TARGET)
    assert error.value.reconnect_required
    assert error.value.scanner == TARGET
    assert b"FIN " not in usb.stream
    assert usb.released


def test_semantic_payload_error_is_synchronized_and_can_finalize(monkeypatch):
    usb = ScriptedUsb(b"\x06", frame(b"CAPA", b"#SAVRANGd240d001#---"), frame(b"FIN "))
    install_usb(monkeypatch, usb)
    with pytest.raises(power.PowerSettingsError) as error:
        power.read_power_settings(TARGET)
    assert not error.value.reconnect_required
    assert usb.stream.endswith(b"FIN x0000000")
    assert usb.released


@pytest.mark.parametrize(
    "status", [b"#nrdBUSY#parOK  ", b"#errADF ERR #parOK  ", b"#parFAIL", b"#parLOST"]
)
def test_parameter_negative_status_is_uncertain_but_frame_can_finalize(monkeypatch, status):
    usb = ScriptedUsb(
        b"\x06",
        frame(b"CAPA", CAPS),
        frame(b"RESA", CURRENT),
        frame(b"PARA", status=status),
        frame(b"FIN "),
    )
    install_usb(monkeypatch, usb)
    with pytest.raises(power.PowerWriteUncertainError) as error:
        power.apply_power_settings(TARGET, power.PowerChanges(30, 0))
    assert not error.value.reconnect_required
    assert usb.stream.count(b"PARA") == 1
    assert usb.stream.endswith(b"FIN x0000000")
    assert usb.released


def test_not_ready_none_is_not_a_busy_failure(monkeypatch):
    usb = ScriptedUsb(
        b"\x06", frame(b"CAPA", CAPS, b"#nrdNONE"), frame(b"RESA", CURRENT), frame(b"FIN ")
    )
    install_usb(monkeypatch, usb)
    assert power.read_power_settings(TARGET).sleep_minutes == 10


def test_aligned_unknown_binary_data_is_skipped_structurally(monkeypatch):
    caps = b"#XYZh001Z\0\0\0#SAVRANGd001d240#---"
    usb = ScriptedUsb(b"\x06", frame(b"CAPA", caps), frame(b"RESA", CURRENT), frame(b"FIN "))
    install_usb(monkeypatch, usb)
    snapshot = power.read_power_settings(TARGET)
    assert snapshot.sleep_capability.minimum == 1
    assert snapshot.power_off_capability is None
